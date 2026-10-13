import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import TIMEZONE, prepare_data


def now():
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def today():
    return datetime.now(TIMEZONE).date().isoformat()


class Store:
    def __init__(self, folder: Path):
        prepare_data(folder)
        self.folder = folder
        self.path = folder / "study.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL, digest TEXT UNIQUE NOT NULL,
                    format TEXT NOT NULL, original BLOB NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pages(
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, text TEXT NOT NULL, PRIMARY KEY(document_id,number));
                CREATE TABLE IF NOT EXISTS chunks(
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page INTEGER NOT NULL, section TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id, ordinal);
                CREATE TABLE IF NOT EXISTS reading(
                    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    completed INTEGER NOT NULL DEFAULT 0, offset INTEGER NOT NULL DEFAULT 0,
                    favorite INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS questions(
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    stem TEXT NOT NULL, options TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT NOT NULL,
                    sources TEXT NOT NULL, origin TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
                    fingerprint TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts(
                    question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE, selected TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(
                    id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    selected TEXT NOT NULL, correct INTEGER NOT NULL, mode TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_question ON attempts(question_id,created_at);
                CREATE TABLE IF NOT EXISTS marks(
                    question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
                    favorite INTEGER NOT NULL DEFAULT 0, uncertain INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                    daily_target INTEGER NOT NULL, days INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                    date TEXT NOT NULL, kind TEXT NOT NULL, target_id TEXT NOT NULL, position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
                    sources TEXT NOT NULL, supported INTEGER NOT NULL, created_at TEXT NOT NULL,
                    model TEXT NOT NULL, fingerprint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get_setting(self, key, fallback=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else fallback

    def setting(self, key, value):
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def query(self, sql, parameters=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, parameters).fetchall()]
