import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .ai.contracts import AiError, ModelRequest
from .ai.provider import ProviderConfig
from .ai.service import (
    answer_request,
    generate_questions,
    get_provider,
    model_public,
    validate_answer,
)
from .backup import export_backup, restore_backup
from .config import DATA_DIR, MAX_UPLOAD, PROJECT_ROOT
from .db import Store, now
from .importing import import_document, save_questions
from .learning import answer_question, create_plan, fingerprint, remember, replay, state
from .retrieval import retrieve
from .security import Security, verify_password


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Payload):
    password: str = Field(max_length=512)


class ModelSettings(Payload):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=4096)
    allow_no_key: bool = False
    json_mode: bool = False
    clear_key: bool = False


class Ask(Payload):
    request_id: str = Field(min_length=16, max_length=64)
    question: str = Field(min_length=2, max_length=2000)
    document_id: str | None = Field(default=None, max_length=64)
    parent_id: str | None = Field(default=None, max_length=64)


class Generate(Payload):
    request_id: str = Field(min_length=16, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    count: int = Field(default=3, ge=1, le=10)
    topic: str = Field(default="", max_length=300)


class Answer(Payload):
    request_id: str = Field(min_length=16, max_length=64)
    selected: list[int] = Field(default_factory=list, max_length=6)
    mode: str = Field(default="answer", pattern="^(answer|reveal)$")


class Reading(Payload):
    offset: int | None = Field(default=None, ge=0, le=10000000)
    completed: bool | None = None
    favorite: bool | None = None


class Mark(Payload):
    favorite: bool | None = None
    uncertain: bool | None = None
    reviewed: bool | None = None


class Draft(Payload):
    selected: list[int] = Field(default_factory=list, max_length=6)


class Plan(Payload):
    request_id: str = Field(min_length=16, max_length=64)
    title: str = Field(default="我的学习计划", min_length=1, max_length=100)
    daily_target: int = Field(default=5, ge=1, le=100)
    document_id: str | None = Field(default=None, max_length=64)


def sse(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


def create_app(folder: Path | None = None, static_dir: Path | None = None):
    app = FastAPI(title="知识库学习助手", docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(folder or DATA_DIR)
    security = Security(store)
    app.state.store = store
    app.state.security = security
    app.state.model_lock = asyncio.Lock()
    login_failures = {}

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin", "")
                allowed = {str(request.base_url).rstrip("/")}
                if value := os.environ.get("STUDY_ORIGIN"):
                    allowed.add(value.rstrip("/"))
                if value := os.environ.get("STUDY_DEV_ORIGIN"):
                    allowed.add(value.rstrip("/"))
                # 浏览器的所有变更请求必须来自当前站点。
                if origin not in allowed:
                    return JSONResponse(
                        {"detail": "请求来源不符，请从当前站点重新操作"}, status_code=403
                    )
            if request.url.path not in {"/api/session", "/api/login", "/api/health"}:
                try:
                    security.require(request)
                except HTTPException as e:
                    return JSONResponse({"detail": e.detail}, status_code=e.status_code)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.exception_handler(AiError)
    async def ai_error(request, error):
        return JSONResponse(
            {"detail": error.message, "code": error.code}, status_code=error.status_code
        )

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    @app.get("/api/session")
    def session(request: Request):
        authenticated = False
        try:
            security.require(request)
            authenticated = True
        except HTTPException:
            pass
        return {
            "authenticated": authenticated,
            "initialized": bool(store.get_setting("password_hash")),
        }

    @app.post("/api/login")
    def login(value: Login, request: Request, response: Response):
        key = request.client.host if request.client else "local"
        failures = [t for t in login_failures.get(key, []) if time.time() - t < 600]
        if len(failures) >= 10:
            raise HTTPException(429, "尝试次数过多，请10分钟后再登录")
        stored = store.get_setting("password_hash")
        if not stored:
            raise HTTPException(503, "尚未初始化，请先按README设置访问密码")
        if not verify_password(value.password, stored):
            login_failures[key] = failures + [time.time()]
            raise HTTPException(401, "访问密码不正确")
        login_failures.pop(key, None)
        response.set_cookie(
            "study_session",
            security.new_session(),
            max_age=7 * 86400,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https" or os.environ.get("STUDY_SECURE_COOKIE") == "1",
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get("study_session", "")
        with store.connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE id=?", (hashlib.sha256(token.encode()).hexdigest(),)
            )
        response.delete_cookie("study_session")
        return {"ok": True}

    @app.get("/api/state")
    def get_state():
        return {**state(store), "model": model_public(store)}

    @app.post("/api/documents")
    async def upload(file: Annotated[UploadFile, File()]):
        raw = await file.read(MAX_UPLOAD + 1)
        return await asyncio.to_thread(import_document, store, raw, file.filename or "资料.txt")

    @app.post("/api/examples")
    def examples():
        file = PROJECT_ROOT / "examples/backup-study.json"
        return import_document(store, file.read_bytes(), file.name, origin="example")

    @app.get("/api/chunks/{chunk_id}")
    def chunk(chunk_id: str):
        found = store.query(
            "SELECT c.*,d.title AS document_title,d.format,d.digest AS version,coalesce(r.offset,0) AS offset FROM chunks c JOIN documents d ON d.id=c.document_id LEFT JOIN reading r ON r.chunk_id=c.id WHERE c.id=?",
            (chunk_id,),
        )
        if not found:
            raise HTTPException(404, "资料片段不存在，可能已被删除")
        return found[0]

    @app.get("/api/search")
    def search(q: str = "", document_id: str | None = None):
        if not 2 <= len(q) <= 2000:
            return []
        return retrieve(store, q, document_id, limit=20)

    @app.get("/api/documents/{document_id}/original")
    def original(document_id: str):
        rows = store.query("SELECT name,original FROM documents WHERE id=?", (document_id,))
        if not rows:
            raise HTTPException(404, "资料不存在")
        return Response(
            rows[0]["original"],
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(rows[0]["name"])
            },
        )

    @app.delete("/api/documents/{document_id}")
    def remove_document(document_id: str):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM tasks WHERE target_id IN (SELECT id FROM chunks WHERE document_id=?) OR target_id IN (SELECT id FROM questions WHERE document_id=?)",
                (document_id, document_id),
            )
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
        return {"ok": True}

    @app.put("/api/reading/{chunk_id}")
    def reading(chunk_id: str, value: Reading):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM chunks WHERE id=?", (chunk_id,)).fetchone():
                raise HTTPException(404, "资料不存在")
            old = db.execute("SELECT * FROM reading WHERE chunk_id=?", (chunk_id,)).fetchone()
            old = dict(old) if old else {"completed": 0, "offset": 0, "favorite": 0}
            changes = value.model_dump(exclude_none=True)
            old.update(changes)
            db.execute(
                "INSERT INTO reading VALUES(?,?,?,?,?) ON CONFLICT(chunk_id) DO UPDATE SET completed=excluded.completed,offset=excluded.offset,favorite=excluded.favorite,updated_at=excluded.updated_at",
                (chunk_id, int(old["completed"]), old["offset"], int(old["favorite"]), now()),
            )
        store.setting("last_chunk", chunk_id)
        return {"ok": True}

    @app.get("/api/last-position")
    def last_position():
        return {
            "chunk_id": store.get_setting("last_chunk", ""),
            "question_id": store.get_setting("last_question", ""),
        }

    @app.get("/api/backup")
    def backup():
        return Response(
            json.dumps(export_backup(store), ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=study-backup.json"},
        )

    @app.post("/api/backup/restore")
    async def restore(file: Annotated[UploadFile, File()]):
        raw = await file.read(100 * 1024 * 1024 + 1)
        if len(raw) > 100 * 1024 * 1024:
            raise HTTPException(413, "备份最多100MB；更大资料库请备份整个服务数据目录")
        return await asyncio.to_thread(restore_backup, store, raw)

    @app.get("/api/questions/{question_id}/result")
    def last_result(question_id: str):
        with store.connect() as db:
            if db.execute("SELECT 1 FROM drafts WHERE question_id=?", (question_id,)).fetchone():
                return None
            latest = db.execute(
                "SELECT id FROM attempts WHERE question_id=? ORDER BY rowid DESC LIMIT 1",
                (question_id,),
            ).fetchone()
            result = (
                db.execute("SELECT result FROM operations WHERE id=?", (latest[0],)).fetchone()
                if latest
                else None
            )
            return json.loads(result[0]) if result else None

    @app.put("/api/questions/{question_id}/draft")
    def draft(question_id: str, value: Draft):
        with store.connect() as db:
            row = db.execute("SELECT options FROM questions WHERE id=?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(404, "题目不存在")
            if len(set(value.selected)) != len(value.selected) or not all(
                type(i) is int and 0 <= i < len(json.loads(row[0])) for i in value.selected
            ):
                raise HTTPException(422, "选项无效")
            db.execute(
                "INSERT INTO drafts VALUES(?,?) ON CONFLICT(question_id) DO UPDATE SET selected=excluded.selected",
                (question_id, json.dumps(value.selected)),
            )
        store.setting("last_question", question_id)
        return {"ok": True}

    @app.post("/api/questions/{question_id}/answer")
    def answer(question_id: str, value: Answer):
        return answer_question(store, question_id, value.selected, value.request_id, value.mode)

    @app.put("/api/questions/{question_id}/marks")
    def marks(question_id: str, value: Mark):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM questions WHERE id=?", (question_id,)).fetchone():
                raise HTTPException(404, "题目不存在")
            old = db.execute("SELECT * FROM marks WHERE question_id=?", (question_id,)).fetchone()
            old = dict(old) if old else {"favorite": 0, "uncertain": 0}
            changes = value.model_dump(exclude_none=True)
            if "reviewed" in changes:
                db.execute(
                    "UPDATE questions SET reviewed=? WHERE id=?",
                    (int(changes.pop("reviewed")), question_id),
                )
            old.update(changes)
            db.execute(
                "INSERT INTO marks VALUES(?,?,?) ON CONFLICT(question_id) DO UPDATE SET favorite=excluded.favorite,uncertain=excluded.uncertain",
                (question_id, int(old["favorite"]), int(old["uncertain"])),
            )
        return {"ok": True}

    @app.post("/api/plans")
    def plan(value: Plan):
        return create_plan(
            store, value.title, value.daily_target, value.document_id, value.request_id
        )

    @app.put("/api/model")
    def save_model(value: ModelSettings):
        previous = store.get_setting("model", {})
        if (
            previous.get("encrypted_key")
            and value.base_url.rstrip("/") != previous.get("base_url")
            and not value.api_key
            and not value.clear_key
        ):
            raise HTTPException(
                422, "模型地址变更，请重新填写密钥；无密钥的本地模型请选择清除旧密钥"
            )
        encrypted = (
            security.encrypt(value.api_key)
            if value.api_key
            else ""
            if value.clear_key
            else previous.get("encrypted_key", "")
        )
        key = security.decrypt(encrypted) if encrypted else ""
        ProviderConfig(
            base_url=value.base_url.rstrip("/"),
            model=value.model.strip(),
            api_key=key,
            allow_no_key=value.allow_no_key,
        )
        if not key and not value.allow_no_key:
            raise HTTPException(422, "请填写API密钥；本地无需密钥的服务可勾选相应选项")
        store.setting(
            "model",
            {
                "base_url": value.base_url.rstrip("/"),
                "model": value.model.strip(),
                "encrypted_key": encrypted,
                "allow_no_key": value.allow_no_key,
                "json_mode": value.json_mode,
            },
        )
        return model_public(store)

    @app.post("/api/model/test")
    async def test_model():
        provider, _ = get_provider(store, security)
        result = await provider.complete(
            ModelRequest([{"role": "user", "content": "请只回复：连接正常"}], "connection_test")
        )
        if not result.text.strip():
            raise HTTPException(502, "模型返回空内容，请检查配置")
        return {"ok": True, "model": result.model, "message": "已收到模型的真实回复"}

    @app.post("/api/ask")
    async def ask(value: Ask):
        payload = value.model_dump(exclude={"request_id"})
        with store.connect() as db:
            previous = replay(db, value.request_id, "ask", payload)
        if previous:

            async def existing():
                yield sse({"type": "done", "chat": previous, "replayed": True})

            return StreamingResponse(existing(), media_type="text/event-stream")
        if app.state.model_lock.locked():
            raise HTTPException(429, "已有模型请求正在处理，请等待或先停止当前问答")
        parent = None
        if value.parent_id:
            rows = store.query("SELECT question,answer FROM chats WHERE id=?", (value.parent_id,))
            if not rows:
                raise HTTPException(404, "上一次问答不存在，请重新提问")
            parent = rows[0]
        search_text = value.question + (
            " " + parent["question"] + " " + parent["answer"][:1000] if parent else ""
        )
        sources = retrieve(store, search_text, value.document_id)
        provider = get_provider(store, security)[0] if sources else None

        async def generate():
            async with app.state.model_lock:
                try:
                    text = ""
                    if not sources:
                        text = "当前资料未找到相关内容。请调整关键词、选择其他资料，或先导入包含这项知识的原文。"
                    else:
                        yield sse({"type": "status", "message": "正在根据资料生成回答"})
                        finish = None
                        async for delta in provider.stream(
                            answer_request(value.question, sources, parent)
                        ):
                            if delta.text:
                                text += delta.text
                                if len(text) > 16000:
                                    raise AiError(
                                        "answer_too_large",
                                        "回答过长，本次未保存，请缩小提问范围",
                                        502,
                                    )
                                yield sse({"type": "delta", "text": delta.text})
                            if delta.finish_reason:
                                finish = delta.finish_reason
                        if finish not in {"stop", "end_turn"} or not text.strip():
                            raise AiError(
                                "incomplete_answer", "回答不完整，本次未保存，请重试", 502
                            )
                    citations, supported = validate_answer(text, sources)
                    result = {
                        "id": value.request_id,
                        "question": value.question,
                        "answer": text,
                        "sources": citations,
                        "supported": supported,
                        "created_at": now(),
                        "model": provider.config.model if provider else "未调用模型",
                    }
                    with store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        if cached := replay(db, value.request_id, "ask", payload):
                            result = cached
                        else:
                            db.execute(
                                "INSERT INTO chats VALUES(?,?,?,?,?,?,?,?)",
                                (
                                    result["id"],
                                    value.question,
                                    text,
                                    json.dumps(citations, ensure_ascii=False),
                                    int(supported),
                                    result["created_at"],
                                    result["model"],
                                    fingerprint(payload),
                                ),
                            )
                            remember(db, value.request_id, "ask", payload, result)
                    yield sse({"type": "done", "chat": result})
                except AiError as error:
                    yield sse({"type": "error", "message": error.message, "code": error.code})
                except Exception:
                    yield sse({"type": "error", "message": "本次回答未保存，请检查连接后重试"})

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.post("/api/questions/generate")
    async def generate_bank(value: Generate):
        payload = value.model_dump(exclude={"request_id"})
        with store.connect() as db:
            previous = replay(db, value.request_id, "generate", payload)
        if previous:
            return previous
        if app.state.model_lock.locked():
            raise HTTPException(429, "已有模型请求正在处理，请稍后重试")
        provider, json_mode = get_provider(store, security)
        if value.topic:
            sources = retrieve(store, value.topic, value.document_id)
        else:
            sources = store.query(
                "SELECT c.*,d.title AS document_title FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.document_id=? ORDER BY c.ordinal LIMIT 8",
                (value.document_id,),
            )
            for i, source in enumerate(sources):
                source["label"] = f"S{i + 1}"
        if not sources:
            raise HTTPException(422, "未找到可用于出题的资料，请调整主题")
        async with app.state.model_lock:
            questions = await generate_questions(provider, json_mode, sources, value.count)
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if previous := replay(db, value.request_id, "generate", payload):
                    return previous
                ids = save_questions(db, value.document_id, questions, now())
                result = {
                    "ids": ids,
                    "created": len(ids),
                    "duplicates": len(questions) - len(ids),
                    "review_status": "待人工核对",
                }
                remember(db, value.request_id, "generate", payload, result)
            return result

    static_path = static_dir or PROJECT_ROOT / "frontend/dist"
    if static_path.is_dir():
        app.mount("/", StaticFiles(directory=static_path, html=True), name="frontend")
    else:

        @app.get("/")
        def missing_frontend():
            return JSONResponse(
                {"detail": "前端尚未构建，请在项目根目录运行 npm ci 与 npm run build"},
                status_code=503,
            )

    return app


app = create_app()
