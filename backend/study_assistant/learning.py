"""学习记录、错题与计划由确定性规则管理，模型不能直接修改完成状态。"""

import hashlib
import json
import math
import uuid
from datetime import date, timedelta

from fastapi import HTTPException

from .db import now, today


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def replay(db, operation_id, kind, payload):
    record = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
    if not record:
        return None
    if record["kind"] != kind or record["fingerprint"] != fingerprint(payload):
        raise HTTPException(409, "同一操作编号不能提交不同内容，请刷新后重试")
    return json.loads(record["result"])


def remember(db, operation_id, kind, payload, result):
    db.execute(
        "INSERT INTO operations VALUES(?,?,?,?)",
        (operation_id, kind, fingerprint(payload), json.dumps(result, ensure_ascii=False)),
    )


def latest_attempts(db):
    rows = db.execute("SELECT * FROM attempts WHERE mode='answer' ORDER BY rowid").fetchall()
    return {r["question_id"]: dict(r) for r in rows}


def state(store):
    with store.connect() as db:
        documents = [
            dict(r)
            for r in db.execute("""SELECT d.id,d.name,d.title,d.format,d.created_at,d.digest,
            (SELECT count(*) FROM chunks WHERE document_id=d.id) AS chunk_count,
            (SELECT count(*) FROM questions WHERE document_id=d.id) AS question_count
            FROM documents d ORDER BY d.created_at,d.id""")
        ]
        chunks = [
            dict(r)
            for r in db.execute("""SELECT c.id,c.document_id,c.page,c.section,c.ordinal,
            coalesce(r.completed,0) AS completed,coalesce(r.offset,0) AS offset,
            coalesce(r.favorite,0) AS favorite,r.updated_at FROM chunks c LEFT JOIN reading r ON r.chunk_id=c.id
            ORDER BY c.document_id,c.ordinal""")
        ]
        latest = latest_attempts(db)
        questions = []
        for r in db.execute("""SELECT q.*,coalesce(m.favorite,0) AS favorite,coalesce(m.uncertain,0) AS uncertain,
            coalesce(d.selected,'[]') AS draft FROM questions q LEFT JOIN marks m ON m.question_id=q.id
            LEFT JOIN drafts d ON d.question_id=q.id ORDER BY q.created_at,q.id"""):
            row = dict(r)
            # 未提交时不向浏览器发送标准答案和解析。
            row["multiple"] = len(json.loads(row.pop("answer"))) > 1
            row["revealed"] = bool(
                db.execute(
                    "SELECT 1 FROM attempts WHERE question_id=? AND mode='reveal' LIMIT 1",
                    (row["id"],),
                ).fetchone()
            )
            row.pop("explanation")
            row.pop("fingerprint")
            row["options"] = json.loads(row["options"])
            row["sources"] = json.loads(row["sources"])
            row["draft"] = json.loads(row["draft"])
            row["latest"] = latest.get(row["id"])
            if row["latest"]:
                row["latest"]["selected"] = json.loads(row["latest"]["selected"])
            questions.append(row)
        active = db.execute("SELECT value FROM settings WHERE key='active_plan'").fetchone()
        active_id = json.loads(active[0]) if active else ""
        plan = db.execute("SELECT * FROM plans WHERE id=?", (active_id,)).fetchone()
        complete_reading = {c["id"] for c in chunks if c["completed"]}
        tasks = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM tasks WHERE plan_id=? ORDER BY date,position", (active_id,)
            )
        ]
        for task in tasks:
            task["completed"] = task["target_id"] in (
                complete_reading if task["kind"] == "reading" else latest
            )
        practiced = len(latest)
        right = sum(bool(a["correct"]) for a in latest.values())
        completed_today = [t for t in tasks if t["date"] == today() and t["completed"]]
        attempts_today = db.execute(
            "SELECT count(*) FROM attempts WHERE mode='answer' AND substr(created_at,1,10)=?",
            (today(),),
        ).fetchone()[0]
        chats = [dict(r) for r in db.execute("SELECT * FROM chats ORDER BY rowid DESC LIMIT 100")]
        for chat in chats:
            chat["sources"] = json.loads(chat["sources"])
            chat.pop("fingerprint")
        wrong = [q["id"] for q in questions if q["latest"] and not q["latest"]["correct"]]
        return {
            "documents": documents,
            "chunks": chunks,
            "questions": questions,
            "chats": chats,
            "plan": dict(plan) if plan else None,
            "tasks": tasks,
            "date": today(),
            "stats": {
                "read": len(complete_reading),
                "chunks": len(chunks),
                "practiced": practiced,
                "questions": len(questions),
                "correct": right,
                "wrong": len(wrong),
                "attempts_today": attempts_today,
                "completed_today": len(completed_today),
            },
            "wrong_question_ids": wrong,
        }


def answer_question(store, question_id, selected, operation_id, mode="answer"):
    payload = {"question_id": question_id, "selected": sorted(selected), "mode": mode}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if previous := replay(db, operation_id, "answer", payload):
            return previous
        row = db.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if not row:
            raise HTTPException(404, "题目不存在")
        options = json.loads(row["options"])
        correct_answer = json.loads(row["answer"])
        if mode == "answer" and (
            not selected
            or len(set(selected)) != len(selected)
            or not all(type(i) is int and 0 <= i < len(options) for i in selected)
        ):
            raise HTTPException(422, "请选择有效答案")
        correct = mode == "answer" and sorted(selected) == correct_answer
        result = {
            "question_id": question_id,
            "answer": correct_answer,
            "selected": sorted(selected),
            "correct": correct,
            "mode": mode,
            "explanation": row["explanation"],
            "sources": json.loads(row["sources"]),
            "reference_only": row["origin"] == "ai" and not row["reviewed"],
        }
        db.execute(
            "INSERT INTO attempts VALUES(?,?,?,?,?,?)",
            (operation_id, question_id, json.dumps(selected), int(correct), mode, now()),
        )
        db.execute("DELETE FROM drafts WHERE question_id=?", (question_id,))
        remember(db, operation_id, "answer", payload, result)
        return result


def create_plan(store, title, daily_target, document_id, operation_id):
    payload = {"title": title, "daily_target": daily_target, "document_id": document_id}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if previous := replay(db, operation_id, "plan", payload):
            return previous
        documents = db.execute(
            "SELECT id FROM documents"
            + (" WHERE id=?" if document_id else "")
            + " ORDER BY created_at,id",
            (document_id,) if document_id else (),
        ).fetchall()
        latest = latest_attempts(db)
        items = []
        for doc in documents:
            for chunk in db.execute(
                "SELECT c.id FROM chunks c LEFT JOIN reading r ON r.chunk_id=c.id WHERE c.document_id=? AND coalesce(r.completed,0)=0 ORDER BY c.ordinal",
                (doc[0],),
            ):
                items.append(("reading", chunk[0]))
            for question in db.execute(
                "SELECT id FROM questions WHERE document_id=? ORDER BY created_at,id", (doc[0],)
            ):
                if question[0] not in latest:
                    items.append(("question", question[0]))
        if not items:
            raise HTTPException(422, "没有未完成的新学内容，可以到错题复习或先导入资料")
        days = math.ceil(len(items) / daily_target)
        if days > 365:
            raise HTTPException(422, "计划超过365天，请缩小资料范围或提高每日学习项数")
        plan_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO plans VALUES(?,?,?,?,?)", (plan_id, title, now(), daily_target, days)
        )
        start = date.fromisoformat(today())
        tasks = [
            (
                uuid.uuid4().hex,
                plan_id,
                (start + timedelta(days=i // daily_target)).isoformat(),
                kind,
                target,
                i,
            )
            for i, (kind, target) in enumerate(items)
        ]
        db.executemany("INSERT INTO tasks VALUES(?,?,?,?,?,?)", tasks)
        db.execute(
            "INSERT INTO settings VALUES('active_plan',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(plan_id),),
        )
        result = {"id": plan_id, "days": days, "tasks": len(tasks), "end_date": tasks[-1][2]}
        remember(db, operation_id, "plan", payload, result)
        return result
