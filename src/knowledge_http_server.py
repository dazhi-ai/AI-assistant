"""极简 HTTP 服务：供外部定时 POST 写入知识库（无第三方依赖）。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from src.knowledge_store import KnowledgeStore

logger = logging.getLogger(__name__)


def _http_response(status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> bytes:
    """拼 HTTP/1.1 响应（短连接）。"""
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 413: "Payload Too Large"}.get(
        status, "Error"
    )
    headers = [
        f"HTTP/1.1 {status} {reason}\r\n",
        f"Content-Length: {len(body)}\r\n",
        f"Content-Type: {content_type}\r\n",
        "Connection: close\r\n",
        "\r\n",
    ]
    return "".join(headers).encode("ascii") + body


def _parse_headers(header_block: bytes) -> dict[str, str]:
    """解析请求头为大小写不敏感字典（键存小写）。"""
    out: dict[str, str] = {}
    for line in header_block.decode("latin-1", errors="replace").split("\r\n"):
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip().lower()] = v.strip()
    return out


def _check_token(headers: dict[str, str], expected: str) -> bool:
    """支持 Authorization: Bearer <token> 或 X-Knowledge-Token: <token>。"""
    if not expected:
        return False
    x = headers.get("x-knowledge-token", "")
    if x == expected:
        return True
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() == expected
    return False


async def _read_http_request(reader: asyncio.StreamReader, max_body: int) -> tuple[str, str, dict[str, str], bytes]:
    """
    读取一次 HTTP/1.1 请求。

    Returns:
        method, path, headers_lower, body
    """
    first = await reader.readline()
    if not first:
        return "", "", {}, b""
    try:
        request_line = first.decode("latin-1").strip()
    except UnicodeDecodeError:
        return "", "", {}, b""
    parts = request_line.split()
    if len(parts) < 2:
        return "", "", {}, b""
    method, path = parts[0], parts[1]

    header_bytes = bytearray()
    while True:
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        header_bytes.extend(line)
        if len(header_bytes) > 65536:
            break

    headers = _parse_headers(bytes(header_bytes))
    cl_raw = headers.get("content-length", "0")
    try:
        content_length = int(cl_raw)
    except ValueError:
        content_length = 0
    if content_length < 0:
        content_length = 0
    if content_length > max_body:
        return method, path, headers, b"__TOO_LARGE__"

    body = await reader.read(content_length) if content_length else b""
    return method, path, headers, body


def make_knowledge_http_handler(
    store: KnowledgeStore,
    ingest_token: str,
    *,
    max_body_bytes: int = 512_000,
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
    """
    工厂：返回 asyncio.start_server 使用的 client_connected_cb。

    路由：
      GET  /v1/knowledge/health  — 无需鉴权，返回 {"ok":true}
      POST /v1/knowledge/ingest   — 需 Bearer 或 X-Knowledge-Token
    """

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            method, path, headers, body = await _read_http_request(reader, max_body_bytes)
            parsed = urlparse(path)
            route = parsed.path.rstrip("/") or "/"

            if method == "GET" and route == "/v1/knowledge/health":
                payload = json.dumps({"ok": True, "service": "knowledge-ingest"}, ensure_ascii=False).encode("utf-8")
                writer.write(_http_response(200, payload))
                await writer.drain()
                return

            if method == "POST" and route == "/v1/knowledge/ingest":
                if not _check_token(headers, ingest_token):
                    writer.write(
                        _http_response(
                            401,
                            json.dumps({"ok": False, "error": "unauthorized"}, ensure_ascii=False).encode("utf-8"),
                        )
                    )
                    await writer.drain()
                    return
                if body == b"__TOO_LARGE__":
                    writer.write(
                        _http_response(
                            413,
                            json.dumps({"ok": False, "error": "body_too_large"}, ensure_ascii=False).encode("utf-8"),
                        )
                    )
                    await writer.drain()
                    return
                try:
                    data = json.loads(body.decode("utf-8") if body else "{}")
                except json.JSONDecodeError:
                    writer.write(
                        _http_response(
                            400,
                            json.dumps({"ok": False, "error": "invalid_json"}, ensure_ascii=False).encode("utf-8"),
                        )
                    )
                    await writer.drain()
                    return
                content = data.get("content")
                if not isinstance(content, str) or not content.strip():
                    writer.write(
                        _http_response(
                            400,
                            json.dumps({"ok": False, "error": "content_required"}, ensure_ascii=False).encode("utf-8"),
                        )
                    )
                    await writer.drain()
                    return
                title = data.get("title") if isinstance(data.get("title"), str) else ""
                source = data.get("source") if isinstance(data.get("source"), str) else ""
                tags = data.get("tags") if isinstance(data.get("tags"), list) else []
                try:
                    entry = store.append(content, title=title, source=source, tags=tags)
                except ValueError as e:
                    writer.write(
                        _http_response(
                            400,
                            json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"),
                        )
                    )
                    await writer.drain()
                    return
                payload = json.dumps(
                    {"ok": True, "id": entry.id, "stored_at": entry.stored_at},
                    ensure_ascii=False,
                ).encode("utf-8")
                writer.write(_http_response(200, payload))
                await writer.drain()
                logger.info("Knowledge ingested id=%s source=%s", entry.id[:12], entry.source or "-")
                return

            writer.write(
                _http_response(404, json.dumps({"ok": False, "error": "not_found"}, ensure_ascii=False).encode("utf-8"))
            )
            await writer.drain()
        except Exception as exc:
            logger.exception("knowledge http error: %s", exc)
            try:
                writer.write(
                    _http_response(
                        500,
                        json.dumps({"ok": False, "error": "internal_error"}, ensure_ascii=False).encode("utf-8"),
                    )
                )
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    return handle_client


async def start_knowledge_http_server(
    host: str,
    port: int,
    store: KnowledgeStore,
    ingest_token: str,
) -> asyncio.Server:
    """启动 TCP 服务器；与 WebSocket 服务并行运行。"""
    handler = make_knowledge_http_handler(store, ingest_token)
    server = await asyncio.start_server(handler, host=host, port=port)
    logger.info("Knowledge ingest HTTP on http://%s:%s/v1/knowledge/ingest", host, port)
    return server
