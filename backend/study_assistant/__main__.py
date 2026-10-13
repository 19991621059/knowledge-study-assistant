import argparse
import getpass
import sys

import uvicorn

from .config import DATA_DIR
from .db import Store
from .security import Security


def main():
    parser = argparse.ArgumentParser(description="知识库学习助手")
    parser.add_argument("action", choices=["init", "serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.action == "init":
        store = Store(DATA_DIR)
        security = Security(store)
        if store.get_setting("password_hash"):
            print("重新设置密码将使已有登录会话失效，学习记录会保留。")
        first = getpass.getpass("设置访问密码（至少12个字符，不显示输入）：")
        second = getpass.getpass("再次输入：")
        if first != second:
            sys.exit("两次密码不同，未保存")
        try:
            security.set_password(first)
        except ValueError as error:
            sys.exit(str(error))
        print("访问密码已保存，可以启动服务。")
    else:
        if not Store(DATA_DIR).get_setting("password_hash"):
            password = __import__("os").environ.get("STUDY_PASSWORD", "")
            if not password:
                sys.exit("请先执行 python -m study_assistant init 设置访问密码")
            Security(Store(DATA_DIR))
        uvicorn.run("study_assistant.main:app", host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
