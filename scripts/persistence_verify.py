"""核对真实服务重启后的学习状态；恢复仅用于另一套空资料库。"""

import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["snapshot", "check", "restore"])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, default=Path("artifacts/restart-state.json"))
    parser.add_argument("--backup-file", type=Path)
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, headers={"Origin": args.url}, timeout=30) as client:
        login = client.post("/api/login", json={"password": args.password_file.read_text().strip()})
        login.raise_for_status()
        if args.action == "restore":
            if not args.backup_file:
                parser.error("restore需要--backup-file，目标必须是空资料库")
            if client.get("/api/state").json()["documents"]:
                raise RuntimeError("目标已有资料，不执行恢复")
            response = client.post(
                "/api/backup/restore", files={"file": ("backup.json", args.backup_file.read_bytes())}
            )
            response.raise_for_status()
        response = client.get("/api/state")
        response.raise_for_status()
        state = response.json()
        if args.action == "snapshot":
            args.state_file.parent.mkdir(parents=True, exist_ok=True)
            args.state_file.write_text(json.dumps(state, ensure_ascii=False))
            print("已保存重启前状态（不包含访问密码或API密钥）")
            return
        expected = json.loads(args.state_file.read_text())
        if args.action == "restore":
            # 学习备份故意排除模型凭据，恢复后需要重新配置模型。
            expected["model"] = state["model"]
            assert not state["model"]["configured"] and not state["model"]["has_key"]
        assert state == expected, "状态与快照不一致，请检查资料、阅读、作答、计划及问答记录"
        print("已验证：资料、阅读位置、作答、收藏、计划和问答完整保留")
        if args.action == "check":
            print("已验证：模型配置和已保存密钥状态在服务重启后保留")


if __name__ == "__main__":
    main()
