"""检查Git暂存区发布内容；可传自己的私有密钥文件进行精确值比对，不打印敏感值。"""

import argparse
import json
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-file", type=Path, action="append", default=[])
    args = parser.parse_args()
    secrets = []
    for file in args.secret_file:
        raw = file.read_bytes().strip()
        if file.suffix == ".json":
            value = json.loads(raw)
            raw = str(value.get("api_key", "")).encode()
        if len(raw) < 12:
            raise RuntimeError("私有值太短或为空，不能可靠核对")
        secrets.append(raw)
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    failures = []
    total = 0
    pattern = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{30,})")
    for name in filter(None, paths):
        path = Path(name)
        if any(p in {"data", "artifacts", "node_modules", ".venv", "test-results"} for p in path.parts) or (
            path.name.startswith(".env") and path.name != ".env.example"
        ) or path.suffix in {".pem", ".p12", ".jks", ".sqlite3", ".key"}:
            failures.append(name + ": 私有或可重建文件")
        raw = subprocess.check_output(["git", "show", ":" + name])
        total += len(raw)
        if len(raw) > 10 * 1024 * 1024:
            failures.append(name + ": 超过10MB，请核对发布必要性")
        if any(secret in raw for secret in secrets) or pattern.search(raw):
            failures.append(name + ": 发现疑似凭据值")
        if re.search(rb"/Users/[A-Za-z0-9._-]+/", raw) and path.suffix not in {".png", ".gif"}:
            failures.append(name + ": 本机绝对路径")
    if failures:
        raise RuntimeError("发布检查未通过：\n" + "\n".join(failures))
    print(f"暂存区检查通过：{len(list(filter(None, paths)))}个文件，共{total}字节，无私有目录或已知凭据值")


if __name__ == "__main__":
    main()
