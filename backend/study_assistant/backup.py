import base64
import json
import sqlite3

from fastapi import HTTPException

TABLES = (
    "documents",
    "pages",
    "chunks",
    "reading",
    "questions",
    "drafts",
    "attempts",
    "marks",
    "plans",
    "tasks",
    "chats",
    "operations",
)
SAFE_SETTINGS = ("active_plan", "last_chunk", "last_question")


def export_backup(store):
    with store.connect() as db:
        db.execute("BEGIN")
        result = {"format": "study-backup-v1", "tables": {}, "settings": {}}
        for table in TABLES:
            rows = [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
            if table == "documents":
                for row in rows:
                    row["original"] = base64.b64encode(row["original"]).decode()
            result["tables"][table] = rows
        for key in SAFE_SETTINGS:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row:
                result["settings"][key] = row[0]
        # 密码、会话、模型密钥和加密主密钥均不进入可下载备份。
        return result


def restore_backup(store, raw):
    try:
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or value.get("format") != "study-backup-v1"
            or set(value["tables"]) != set(TABLES)
            or not set(value.get("settings", {})) <= set(SAFE_SETTINGS)
        ):
            raise ValueError
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM documents LIMIT 1").fetchone():
                raise HTTPException(
                    409, "为保护已有记录，备份只恢复到空资料库；请使用一个新的数据目录"
                )
            for table in TABLES:
                rows = value["tables"][table]
                if not isinstance(rows, list):
                    raise ValueError
                columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        raise ValueError
                    if table == "documents":
                        row["original"] = base64.b64decode(row["original"], validate=True)
                    db.execute(
                        f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                        [row[key] for key in columns],
                    )
            for key, setting in value.get("settings", {}).items():
                json.loads(setting)
                db.execute(
                    "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, setting),
                )
        return {"ok": True, "documents": len(value["tables"]["documents"])}
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, sqlite3.Error):
        raise HTTPException(422, "备份格式或引用关系无效，未恢复任何数据") from None
