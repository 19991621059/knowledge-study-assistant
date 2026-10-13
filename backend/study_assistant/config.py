import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.environ.get("STUDY_PROJECT_ROOT", ROOT.parent)).resolve()
DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", PROJECT_ROOT / "data")).resolve()
TIMEZONE = ZoneInfo(os.environ.get("STUDY_TIMEZONE", "Asia/Shanghai"))
MAX_UPLOAD = 20 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_PAGES = 500
MAX_CHUNKS = 4000


def prepare_data(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
