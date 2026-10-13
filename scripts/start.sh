#!/usr/bin/env sh
set -eu
STUDY_PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$STUDY_PROJECT_DIR"
exec .venv/bin/python -m study_assistant serve
