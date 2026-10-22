"""MCP 联调探针。

用途：拿到真实的 tools/list schema，并安全地试调几个只读工具。
绝不会调用任何写操作（下单 / 领券 / 抽奖 / 取消订单）。

用法：
    set MCD_MCP_TOKEN=你的token      (PowerShell: $env:MCD_MCP_TOKEN="...")
    python scripts/probe_mcp.py

输出：
    控制台摘要 + mcp_tools.json（已被 .gitignore 忽略）
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import MCD_MCP_TOKEN, MCD_MCP_URL, TOOLS_SCHEMA_PATH  # noqa: E402
from app.mcp_client import MCPClient, MCPError  # noqa: E402

# 只读工具，按风险从低到高排列
READ_ONLY_PROBES = [
    ("now-time-info", {}),
    ("list-nutrition-foods", {}),
    ("query-my-account", {}),
    ("available-coupons", {}),
    ("query-my-coupons", {}),
    ("order-list", {}),
    ("campaign-calendar", {}),
]


def _short(text: str, limit: int = 400) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + " …"


async def main() -> int:
    if not MCD_MCP_TOKEN:
        print("未检测到 MCD_MCP_TOKEN。请先设置环境变量，或写入 .env")
        return 2

    print(f"连接 {MCD_MCP_URL} …")
    try:
        async with MCPClient(MCD_MCP_URL, MCD_MCP_TOKEN, timeout=90) as client:
            print("握手成功")
            print(f"  协议版本: {client.protocol_version}")
            print(f"  服务端  : {client.server_info}")
            print(f"  Session : {client.session_id}")

            tools = await client.list_tools()
            print(f"\n发现 {len(tools)} 个工具\n")

            schema_dump = {
                "server": client.server_info,
                "protocolVersion": client.protocol_version,
                "tools": tools,
            }
            TOOLS_SCHEMA_PATH.write_text(
                json.dumps(schema_dump, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"完整 schema 已写入 {TOOLS_SCHEMA_PATH}\n")

            for tool in tools:
                schema = tool.get("inputSchema") or {}
                required = schema.get("required") or []
                props = list((schema.get("properties") or {}).keys())
                print(f"- {tool.get('name')}: {tool.get('title') or ''}")
                print(f"    参数: {props}  必填: {required}")

            print("\n=== 只读试调 ===")
            for name, args in READ_ONLY_PROBES:
                if not any(t.get("name") == name for t in tools):
                    print(f"\n[{name}] 服务端未提供，跳过")
                    continue
                try:
                    result = await client.call_tool(name, args)
                    payload = json.dumps(result, ensure_ascii=False, default=str)
                    print(f"\n[{name}] 成功，返回 {len(payload)} 字符")
                    print("  预览:", _short(payload))
                except MCPError as exc:
                    print(f"\n[{name}] 失败: {exc}")
                except Exception as exc:  # noqa: BLE001
                    print(f"\n[{name}] 异常: {type(exc).__name__}: {exc}")

    except MCPError as exc:
        print(f"MCP 错误: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"连接失败: {type(exc).__name__}: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
