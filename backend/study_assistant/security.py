import base64
import hashlib
import hmac
import os
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request

from .db import Store


def password_hash(password: str, salt: bytes | None = None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.urlsafe_b64encode(salt + digest).decode()


def verify_password(password, stored):
    try:
        raw = base64.urlsafe_b64decode(stored)
        return hmac.compare_digest(password_hash(password, raw[:16]), stored)
    except (ValueError, TypeError):
        return False


class Security:
    def __init__(self, store: Store):
        self.store = store
        path = store.folder / "secret.key"
        if not path.exists():
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
        path.chmod(0o600)
        self.fernet = Fernet(path.read_bytes())
        password = os.environ.get("STUDY_PASSWORD", "")
        if password and not store.get_setting("password_hash"):
            self.set_password(password)

    def set_password(self, password):
        if len(password) < 12 or password in {"change-me-please", "your-password-here"}:
            raise ValueError("访问密码至少12个字符，请使用自己的密码")
        self.store.setting("password_hash", password_hash(password))
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions")

    def encrypt(self, value: str):
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str):
        try:
            return self.fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            raise HTTPException(503, "模型密钥无法解密，请在设置中重新填写") from None

    def require(self, request: Request):
        token = request.cookies.get("study_session", "")
        digest = hashlib.sha256(token.encode()).hexdigest()
        rows = self.store.query("SELECT expires FROM sessions WHERE id=?", (digest,))
        if not token or not rows or rows[0]["expires"] < time.time():
            raise HTTPException(401, "请先登录")

    def new_session(self):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES(?,?)", (digest, int(time.time()) + 7 * 86400))
        return token
