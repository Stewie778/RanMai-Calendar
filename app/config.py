"""运行配置。

Token 只从环境变量 / 本地 .env 读取，任何情况下都不写入代码或提交到仓库。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RANMAI_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "ranmai.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"
TOOLS_SCHEMA_PATH = BASE_DIR / "mcp_tools.json"


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 解析，不引入额外依赖。已存在的环境变量优先。"""
    path = path or (BASE_DIR / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

MCD_MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn").strip()
MCD_MCP_TOKEN = os.environ.get("MCD_MCP_TOKEN", "").strip()

# auto: 有 Token 就连真服务，没有就走演示数据；=1 强制演示
_DEMO_FLAG = os.environ.get("RANMAI_DEMO", "auto").strip().lower()
DEMO_MODE = _DEMO_FLAG == "1" or not MCD_MCP_TOKEN
LIVE_MODE = not DEMO_MODE

DATA_DIR.mkdir(parents=True, exist_ok=True)
