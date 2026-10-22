"""最小的 MCP Streamable HTTP 客户端。

只依赖 httpx，不引入官方 SDK，方便评审直接读懂整条调用链。
协议要点：
  1. POST initialize，服务端会在响应头返回 Mcp-Session-Id
  2. 发送 notifications/initialized
  3. tools/list 获取工具清单与 inputSchema
  4. tools/call 调用工具
响应可能是 application/json，也可能是 text/event-stream。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

CLIENT_INFO = {"name": "ranmai-calendar", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-06-18"


class MCPError(RuntimeError):
    """MCP 调用失败。"""


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 文本切成 JSON-RPC 消息列表。"""
    events: list[dict] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        raw = "\n".join(buffer)
        buffer.clear()
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            pass

    for line in text.splitlines():
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
        elif not line.strip():
            flush()
    flush()
    return events


def normalize_result(result: Any) -> Any:
    """把 tools/call 的 result 归一化成 Python 数据。"""
    if not isinstance(result, dict):
        return result

    if result.get("structuredContent") is not None:
        return result["structuredContent"]

    content = result.get("content") or []
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                texts.append(text)
    if len(texts) == 1:
        return texts[0]
    if texts:
        return {"text": "\n".join(texts)}
    return result


class MCPClient:
    def __init__(self, url: str, token: str, timeout: float = 60.0) -> None:
        if not token:
            raise MCPError("缺少 MCP Token")
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.server_info: dict = {}
        self._http: httpx.AsyncClient | None = None
        self._id = 0

    async def __aenter__(self) -> "MCPClient":
        self._http = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        try:
            await self.initialize()
        except Exception:
            await self._http.aclose()
            self._http = None
            raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise MCPError("客户端尚未启动，请使用 async with")
        return self._http

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    async def _post(self, payload: dict) -> dict | None:
        response = await self.http.post(self.url, headers=self._headers(), json=payload)

        if response.status_code == 401:
            raise MCPError("401：MCP Token 无效、已过期或未提供")
        if response.status_code == 429:
            raise MCPError("429：触发限流（600 次/分钟），请降低调用频率")
        response.raise_for_status()

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            events = _parse_sse(response.text)
        elif not response.content:
            return None
        else:
            try:
                return response.json()
            except json.JSONDecodeError:
                events = _parse_sse(response.text)

        request_id = payload.get("id")
        for event in events:
            if event.get("id") == request_id:
                return event
        return events[-1] if events else None

    async def notify(self, method: str, params: dict | None = None) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def initialize(self) -> dict:
        message = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
        )
        if not message:
            raise MCPError("initialize 无响应")
        if "error" in message:
            raise MCPError(f"initialize 失败: {message['error']}")

        result = message.get("result") or {}
        self.protocol_version = result.get("protocolVersion") or PROTOCOL_VERSION
        self.server_info = result.get("serverInfo") or {}
        await self.notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor: str | None = None
        for _ in range(20):
            params = {"cursor": cursor} if cursor else {}
            message = await self._post(
                {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": params}
            )
            if not message or "error" in message:
                raise MCPError(f"tools/list 失败: {message}")
            result = message.get("result") or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        message = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if message is None:
            raise MCPError(f"{name} 无响应")
        if "error" in message:
            raise MCPError(f"{name} 调用失败: {message['error']}")

        result = message.get("result") or {}
        if result.get("isError"):
            detail = normalize_result(result)
            raise MCPError(f"{name} 返回错误: {detail}")
        return normalize_result(result)


async def open_client(url: str, token: str) -> MCPClient:
    """辅助函数：返回已初始化的客户端（调用方负责 aclose）。"""
    client = MCPClient(url, token)
    await client.__aenter__()
    return client
