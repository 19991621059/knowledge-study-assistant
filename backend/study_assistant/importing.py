"""原文件、物理页码和片段稳定身份一起保存；失败导入不写入半份资料。"""

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi import HTTPException
from pypdf import PdfReader

from .config import MAX_CHUNKS, MAX_PAGES, MAX_TEXT, MAX_UPLOAD
from .db import Store, now


def invalid(message):
    raise HTTPException(422, message)


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def extract(raw: bytes, filename: str):
    extension = Path(filename).suffix.lower()
    if not raw or len(raw) > MAX_UPLOAD:
        invalid("资料不能为空，单个文件最多20MB")
    bank = []
    title = Path(filename).stem
    try:
        if extension in {".txt", ".md"}:
            text = raw.decode("utf-8-sig")
            if "\x00" in text:
                invalid("这不是有效的文字资料")
            # 文本分段是定位段号，不冒充原书页码。
            pages = [(1, text)]
            first = re.search(r"^#\s+(.+)$", text, re.M)
            if first:
                title = first[1].strip()
        elif extension == ".pdf":
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                invalid("请先解除 PDF 密码后再导入")
            if len(reader.pages) > MAX_PAGES:
                invalid("PDF最多500页，请先分卷")
            pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
            if any(not text.strip() for _, text in pages):
                invalid("PDF有无法提取文字的页面，请先做OCR或导出文字；本版不自动识别扫描图片")
        elif extension == ".docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(e.file_size for e in archive.infolist()) > 40 * 1024 * 1024:
                    invalid("DOCX解压后过大，请先分卷")
            document = Document(io.BytesIO(raw))
            parts = []
            for block in document.iter_inner_content():
                if isinstance(block, Paragraph) and block.text.strip():
                    parts.append(block.text)
                elif isinstance(block, Table):
                    parts.append("\n".join(" | ".join(c.text for c in row.cells) for row in block.rows))
            pages = [(1, "\n\n".join(parts))]
        elif extension == ".json":
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("format") != "study-bundle-v1":
                invalid("JSON仅支持 study-bundle-v1；格式见examples/backup-study.json")
            title = str(value.get("title", title))[:200]
            source_pages = value.get("pages")
            if not isinstance(source_pages, list) or not 1 <= len(source_pages) <= MAX_PAGES:
                invalid("资料包必须包含1至500段原文")
            pages = [
                (i + 1, p["text"])
                for i, p in enumerate(source_pages)
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            ]
            if len(pages) != len(source_pages):
                invalid("资料包原文格式错误")
            bank = value.get("questions", [])
            if not isinstance(bank, list) or len(bank) > 1000:
                invalid("一个资料包最多1000题")
        else:
            invalid("支持UTF-8 TXT、Markdown、文字PDF、DOCX和study-bundle-v1 JSON")
        total = sum(len(text) for _, text in pages)
        if total > MAX_TEXT:
            invalid("资料文字超过200万字符，请分卷")
        if total < 30 or not all(text.strip() for _, text in pages):
            invalid("可提取文字太少，请检查文件；扫描资料需先做OCR")
        return title[:200], pages, bank, extension[1:]
    except HTTPException:
        raise
    except Exception:
        invalid("文件无法读取，请检查编码、密码或文件完整性")


def split_chunks(document_id: str, pages):
    result = []
    section = "正文"
    for page, text in pages:
        sections = re.split(r"(?m)(?=^#{1,6}\s+)", text)
        for part in sections:
            if not part.strip():
                continue
            match = re.match(r"^#{1,6}\s+([^\n]+)", part)
            if match:
                section = match[1].strip()
            position = 0
            while position < len(part):
                end = min(position + 1000, len(part))
                if end < len(part):
                    boundary = max(
                        part.rfind("\n", position + 650, end), part.rfind("。", position + 650, end)
                    )
                    if boundary > position:
                        end = boundary + 1
                content = part[position:end].strip()
                if content:
                    ordinal = len(result)
                    result.append(
                        {
                            "id": f"{document_id}-{ordinal}",
                            "page": page,
                            "section": section,
                            "ordinal": ordinal,
                            "text": content,
                        }
                    )
                if end >= len(part):
                    break
                position = end - 100
    if len(result) > MAX_CHUNKS:
        invalid("资料分段超过4000段，请先分卷")
    return result


def checked_question(item, chunks, origin):
    if not isinstance(item, dict):
        invalid("题目必须是对象")
    stem = item.get("stem", "")
    options = item.get("options", [])
    answer = item.get("answer", [])
    if isinstance(answer, int) and not isinstance(answer, bool):
        answer = [answer]
    explanation = item.get("explanation", "")
    if (
        not isinstance(stem, str)
        or not 5 <= len(stem.strip()) <= 2000
        or not isinstance(options, list)
        or not 2 <= len(options) <= 6
        or not all(isinstance(o, str) and 0 < len(o.strip()) <= 1000 for o in options)
        or len(set(options)) != len(options)
        or not isinstance(answer, list)
        or not answer
        or not all(type(a) is int and 0 <= a < len(options) for a in answer)
        or len(set(answer)) != len(answer)
        or not isinstance(explanation, str)
        or not 5 <= len(explanation.strip()) <= 4000
    ):
        invalid("题目、选项、答案或解析格式无效；整批未保存，请修正后重试")
    citations = item.get("sources", [])
    if not isinstance(citations, list) or not 1 <= len(citations) <= 4:
        invalid("每题必须有1至4条原文出处")
    verified = []
    for source in citations:
        if not isinstance(source, dict) or not isinstance(source.get("quote"), str):
            invalid("题目出处格式错误")
        quote = source["quote"].strip()
        candidates = [
            c
            for c in chunks
            if (
                source.get("chunk_id") == c["id"]
                or (not source.get("chunk_id") and source.get("page") == c["page"])
            )
        ]
        found = next((c for c in candidates if 8 <= len(quote) <= 800 and quote in c["text"]), None)
        if not found:
            invalid("题目引用无法在原文中找到；整批未保存，请检查资料或重新生成")
        verified.append(
            {
                "chunk_id": found["id"],
                "page": found["page"],
                "section": found["section"],
                "quote": quote,
            }
        )
    return {
        "stem": stem.strip(),
        "options": options,
        "answer": sorted(answer),
        "explanation": explanation.strip(),
        "sources": verified,
        "origin": origin,
        "fingerprint": digest(stem.strip() + json.dumps(options, ensure_ascii=False)),
    }


def save_questions(db, document_id, questions, created):
    ids = []
    for question in questions:
        question_id = digest(document_id + question["fingerprint"])[:24]
        existing = db.execute(
            "SELECT id FROM questions WHERE fingerprint=?", (question["fingerprint"],)
        ).fetchone()
        if existing:
            continue
        db.execute(
            "INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                question_id,
                document_id,
                question["stem"],
                json.dumps(question["options"], ensure_ascii=False),
                json.dumps(question["answer"]),
                question["explanation"],
                json.dumps(question["sources"], ensure_ascii=False),
                question["origin"],
                int(question["origin"] == "example"),
                question["fingerprint"],
                created,
            ),
        )
        ids.append(question_id)
    return ids


def import_document(store: Store, raw: bytes, filename: str, origin="imported"):
    filename = Path(filename.replace("\\", "/")).name[:200] or "资料.txt"
    file_hash = hashlib.sha256(raw).hexdigest()
    with store.connect() as db:
        existing = db.execute("SELECT id FROM documents WHERE digest=?", (file_hash,)).fetchone()
        if existing:
            return {"id": existing[0], "duplicate": True}
    title, pages, bank, format_name = extract(raw, filename)
    document_id = file_hash[:24]
    chunks = split_chunks(document_id, pages)
    checked = [checked_question(item, chunks, origin) for item in bank]
    created = now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id FROM documents WHERE digest=?", (file_hash,)).fetchone()
        if existing:
            return {"id": existing[0], "duplicate": True}
        db.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
            (document_id, filename, title, file_hash, format_name, raw, created),
        )
        db.executemany("INSERT INTO pages VALUES(?,?,?)", [(document_id, p, t) for p, t in pages])
        db.executemany(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
            [
                (c["id"], document_id, c["page"], c["section"], c["ordinal"], c["text"])
                for c in chunks
            ],
        )
        question_ids = save_questions(db, document_id, checked, created)
    return {
        "id": document_id,
        "duplicate": False,
        "chunks": len(chunks),
        "questions": len(question_ids),
    }
