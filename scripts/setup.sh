#!/usr/bin/env sh
set -eu
STUDY_PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$STUDY_PROJECT_DIR"
python3 -c 'import sys; assert sys.version_info >= (3,11), "需要Python 3.11或更新版本"'
node -e 'const v=process.versions.node.split(".").map(Number); if(v[0]<22 || (v[0]===22 && v[1]<13)) throw new Error("需要Node.js 22.13或更新版本")'
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r backend/requirements.lock
.venv/bin/python -m pip install --no-deps -e backend
npm ci
npm run build
if .venv/bin/python -c 'from study_assistant.config import DATA_DIR; from study_assistant.db import Store; import sys; sys.exit(0 if Store(DATA_DIR).get_setting("password_hash") else 1)'; then
    printf '%s\n' '已有访问密码与学习记录，继续保留。'
else
    .venv/bin/python -m study_assistant init
fi
printf '%s\n' '安装完成。运行 sh scripts/start.sh 后打开 http://127.0.0.1:8000'
