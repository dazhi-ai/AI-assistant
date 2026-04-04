"""WebSocket gateway with auth, heartbeat, and tool orchestration."""

import asyncio
import base64
import logging
import re

import websockets
from websockets.asyncio.server import ServerConnection

from plugins.netease_cloud import NeteaseCloudController
from plugins.weather_service import WeatherService
from src.ark_client import ArkClient
from src.assistant_service import AssistantService
from src.knowledge_http_server import start_knowledge_http_server
from src.knowledge_store import KnowledgeStore
from src.asr_service import ASRService
from src.config import Settings
from src.protocol import build_message, parse_message
from src.tool_handler import ToolHandler
from src.tts_service import TTSService


logger = logging.getLogger(__name__)

# 全局平板 WebSocket 连接集合（asyncio 单线程内操作，无需锁）
_tablet_websockets: set = set()


async def _send_message(websocket: ServerConnection, message_type: str, payload: dict, trace_id: str | None = None) -> None:
    """Send one protocol message to the client."""
    logger.info("SEND %s payload_keys=%s", message_type, list(payload.keys()))
    await websocket.send(build_message(message_type, payload, trace_id=trace_id).to_json())


def _detect_model_switch(user_text: str) -> dict | None:
    """Infer model switch target from user natural language."""
    if "换成" not in user_text and "切换" not in user_text:
        return None
    match = re.search(r"(换成|切换到?)(.+)$", user_text)
    style_text = match.group(2).strip() if match else user_text.strip()
    if not style_text:
        style_text = "default"
    model_id = "default"
    if "运动" in style_text:
        model_id = "sport"
    elif "可爱" in style_text:
        model_id = "cute"
    elif "科技" in style_text:
        model_id = "tech"
    return {"model_id": model_id, "style": style_text}


async def _stream_tts_to_client(
    websocket: ServerConnection,
    tts_service: TTSService,
    text: str,
    trace_id: str,
) -> None:
    """Convert text to streaming chunks and push to websocket."""
    if not text or not tts_service.enabled:
        return
    chunk_index = 0
    async for chunk_b64 in tts_service.stream_audio_chunks(text):
        await _send_message(
            websocket,
            "AUDIO_CHUNK",
            {
                "codec": "audio/mpeg",
                "chunk_index": chunk_index,
                "chunk_base64": chunk_b64,
            },
            trace_id=trace_id,
        )
        chunk_index += 1
    if chunk_index == 0 and tts_service.last_error:
        await _send_message(
            websocket,
            "ERROR",
            {"code": "TTS_FAILED", "message": tts_service.last_error},
            trace_id=trace_id,
        )
    await _send_message(
        websocket,
        "AUDIO_END",
        {"total_chunks": chunk_index},
        trace_id=trace_id,
    )


async def _handle_user_text(
    websocket: ServerConnection,
    assistant: AssistantService,
    tts_service: TTSService,
    session_id: str,
    user_text: str,
    trace_id: str,
) -> None:
    """Process one user text through assistant/tooling and emit all events."""
    process_result = await assistant.process_user_text(session_id=session_id, user_text=user_text)
    await _send_message(
        websocket,
        "TEXT",
        {"text": process_result["assistant_text"]},
        trace_id=trace_id,
    )
    model_switch = _detect_model_switch(user_text)
    if model_switch:
        await _send_message(
            websocket,
            "MODEL_SWITCH",
            model_switch,
            trace_id=trace_id,
        )
    for tool_result in process_result["tool_results"]:
        await _send_message(
            websocket,
            "TOOL_RESULT",
            tool_result,
            trace_id=trace_id,
        )
        if tool_result["name"] == "like_music" and tool_result["result"].get("ok"):
            await _send_message(
                websocket,
                "EFFECT",
                {"action": "HEART"},
                trace_id=trace_id,
            )
        if tool_result["name"] == "get_netease_login_qrcode" and tool_result["result"].get("ok"):
            await _send_message(
                websocket,
                "QRCODE",
                {
                    "unikey": tool_result["result"].get("unikey", ""),
                    "qrurl": tool_result["result"].get("qrurl", ""),
                    "qrimg": tool_result["result"].get("qrimg", ""),
                },
                trace_id=trace_id,
            )
        if tool_result["name"] == "play_music" and tool_result["result"].get("ok"):
            await _send_message(
                websocket,
                "AUDIO_URL",
                {"url": tool_result["result"].get("url", "")},
                trace_id=trace_id,
            )
        if tool_result["name"] == "get_weather_forecast" and tool_result["result"].get("ok"):
            await _send_message(
                websocket,
                "WEATHER_CARD",
                {
                    "city": tool_result["result"].get("city", ""),
                    "adm1": tool_result["result"].get("adm1", ""),
                    "adm2": tool_result["result"].get("adm2", ""),
                    "forecast": tool_result["result"].get("forecast", []),
                },
                trace_id=trace_id,
            )
    await _stream_tts_to_client(
        websocket=websocket,
        tts_service=tts_service,
        text=process_result["assistant_text"],
        trace_id=trace_id,
    )


async def handle_client(
    websocket: ServerConnection,
    settings: Settings,
    assistant: AssistantService,
    tts_service: TTSService,
    asr_service: ASRService,
) -> None:
    """Handle one client connection using protocol-based events."""
    # 声明使用模块级全局集合，避免 Python 将函数内赋值操作误判为局部变量
    global _tablet_websockets
    logger.info("Client connected")
    session_id = str(id(websocket))
    authed = settings.ws_token == ""
    is_mirror_source = False  # True 表示此连接来自 xiaozhi-esp32-server 桥接
    audio_input_chunk_count = 0
    audio_input_bytes = bytearray()

    # 默认注册为平板连接，MIRROR_INIT 后会移出
    _tablet_websockets.add(websocket)

    try:
        async for raw_message in websocket:
            logger.info("RAW MSG RECEIVED: %s", raw_message[:120] if isinstance(raw_message, str) else f"<binary {len(raw_message)}B>")
            if not isinstance(raw_message, str):
                await _send_message(websocket, "ERROR", {"code": "BAD_MESSAGE", "message": "Only text messages are supported."})
                continue
            try:
                message = parse_message(raw_message)
            except ValueError as exc:
                await _send_message(websocket, "ERROR", {"code": "BAD_MESSAGE", "message": str(exc)})
                continue

            if message.type == "AUTH":
                token = str(message.payload.get("token", ""))
                if settings.ws_token and token != settings.ws_token:
                    await _send_message(websocket, "ERROR", {"code": "AUTH_FAILED", "message": "Invalid token."}, trace_id=message.trace_id)
                    continue
                authed = True
                await _send_message(websocket, "AUTH_OK", {"message": "Authenticated."}, trace_id=message.trace_id)
                continue

            # 小智桥接握手：无需通过普通 AUTH，使用独立 mirror_token
            if message.type == "MIRROR_INIT":
                token = str(message.payload.get("token", ""))
                if settings.mirror_token and token == settings.mirror_token:
                    is_mirror_source = True
                    _tablet_websockets.discard(websocket)  # 桥接源不列为平板
                    logger.info("Mirror source connected (xiaozhi bridge)")
                    await _send_message(websocket, "MIRROR_OK", {"ok": True}, trace_id=message.trace_id)
                else:
                    await _send_message(websocket, "ERROR", {"code": "MIRROR_AUTH_FAILED", "message": "Invalid mirror_token."}, trace_id=message.trace_id)
                continue

            # 小智 AI 文字回复推送：广播给所有平板连接并生成 TTS
            if message.type == "XIAOZHI_TEXT" and is_mirror_source:
                ai_text = str(message.payload.get("ai_text", "")).strip()
                if ai_text and _tablet_websockets:
                    dead: set = set()
                    for ws in list(_tablet_websockets):
                        try:
                            await _send_message(ws, "TEXT", {"text": ai_text}, trace_id=message.trace_id)
                            await _stream_tts_to_client(
                                websocket=ws,
                                tts_service=tts_service,
                                text=ai_text,
                                trace_id=message.trace_id,
                            )
                        except Exception:  # noqa: BLE001
                            dead.add(ws)
                    _tablet_websockets.difference_update(dead)
                    logger.info("Mirrored xiaozhi text to %d tablet(s): %s", len(_tablet_websockets), ai_text[:40])
                continue

            if not authed:
                await _send_message(
                    websocket,
                    "ERROR",
                    {"code": "UNAUTHORIZED", "message": "Please send AUTH message first."},
                    trace_id=message.trace_id,
                )
                continue

            if message.type == "PING":
                await _send_message(websocket, "PONG", {"ok": True}, trace_id=message.trace_id)
                continue

            if message.type == "AUDIO_INPUT_CHUNK":
                chunk_base64 = str(message.payload.get("chunk_base64", ""))
                if not chunk_base64:
                    await _send_message(
                        websocket,
                        "ERROR",
                        {"code": "BAD_AUDIO_CHUNK", "message": "payload.chunk_base64 is required."},
                        trace_id=message.trace_id,
                    )
                    continue
                try:
                    chunk_bytes = base64.b64decode(chunk_base64, validate=True)
                except Exception:  # noqa: BLE001
                    await _send_message(
                        websocket,
                        "ERROR",
                        {"code": "BAD_AUDIO_CHUNK", "message": "chunk_base64 is not valid base64."},
                        trace_id=message.trace_id,
                    )
                    continue
                audio_input_bytes.extend(chunk_bytes)
                audio_input_chunk_count += 1
                if len(audio_input_bytes) > asr_service.max_audio_bytes:
                    await _send_message(
                        websocket,
                        "ERROR",
                        {
                            "code": "AUDIO_TOO_LARGE",
                            "message": f"Audio input exceeded {asr_service.max_audio_bytes} bytes limit.",
                        },
                        trace_id=message.trace_id,
                    )
                    audio_input_bytes.clear()
                    audio_input_chunk_count = 0
                continue

            if message.type == "AUDIO_INPUT_END":
                if audio_input_chunk_count <= 0:
                    await _send_message(
                        websocket,
                        "ERROR",
                        {"code": "AUDIO_EMPTY", "message": "No AUDIO_INPUT_CHUNK received before AUDIO_INPUT_END."},
                        trace_id=message.trace_id,
                    )
                    continue
                asr_result = await asr_service.transcribe(bytes(audio_input_bytes))
                if not asr_result.get("ok"):
                    await _send_message(
                        websocket,
                        "ERROR",
                        {"code": "ASR_FAILED", "message": asr_result.get("error", "Unknown ASR error")},
                        trace_id=message.trace_id,
                    )
                    audio_input_bytes.clear()
                    audio_input_chunk_count = 0
                    continue
                user_text_from_audio = asr_result.get("text", "").strip()
                await _send_message(
                    websocket,
                    "ASR_RESULT",
                    {
                        "text": user_text_from_audio,
                        "chunks": audio_input_chunk_count,
                        "bytes": len(audio_input_bytes),
                    },
                    trace_id=message.trace_id,
                )
                if user_text_from_audio:
                    await _handle_user_text(
                        websocket=websocket,
                        assistant=assistant,
                        tts_service=tts_service,
                        session_id=session_id,
                        user_text=user_text_from_audio,
                        trace_id=message.trace_id,
                    )
                else:
                    await _send_message(
                        websocket,
                        "ERROR",
                        {"code": "ASR_EMPTY", "message": "ASR returned empty text."},
                        trace_id=message.trace_id,
                    )
                audio_input_bytes.clear()
                audio_input_chunk_count = 0
                continue

            if message.type == "TEXT":
                user_text = str(message.payload.get("text", "")).strip()
                if not user_text:
                    await _send_message(
                        websocket,
                        "ERROR",
                        {"code": "BAD_TEXT", "message": "payload.text is required."},
                        trace_id=message.trace_id,
                    )
                    continue
                await _handle_user_text(
                    websocket=websocket,
                    assistant=assistant,
                    tts_service=tts_service,
                    session_id=session_id,
                    user_text=user_text,
                    trace_id=message.trace_id,
                )
                continue

            await _send_message(
                websocket,
                "ERROR",
                {"code": "UNSUPPORTED_TYPE", "message": f"Unsupported type: {message.type}"},
                trace_id=message.trace_id,
            )
    except websockets.ConnectionClosed:
        logger.info("Client disconnected")
    finally:
        _tablet_websockets.discard(websocket)
        if not is_mirror_source:
            assistant.clear_session(session_id)


async def start_server(settings: Settings) -> None:
    """Start the WebSocket server and keep it running forever."""
    netease = NeteaseCloudController(
        api_base_url=settings.netease_api_url,
        cookie=settings.netease_cookie,
        user_id=settings.netease_user_id,
        favorite_playlist_id=settings.netease_favorite_playlist_id,
        timeout_seconds=settings.request_timeout_seconds,
    )
    await netease.connect()
    if not netease.connected:
        logger.warning("Netease API connectivity check failed at startup.")
    weather = WeatherService(
        api_key=settings.qweather_api_key,
        api_host=settings.qweather_api_host,
        geo_base_url=settings.qweather_geo_base_url,
        weather_base_url=settings.qweather_weather_base_url,
        use_header_auth=bool(settings.qweather_api_host),
        timeout_seconds=settings.request_timeout_seconds,
    )
    if not weather.enabled:
        logger.warning("Weather service is disabled (missing QWEATHER_API_KEY).")
    tool_handler = ToolHandler(netease, weather)
    knowledge_store = KnowledgeStore(settings.knowledge_data_path)
    assistant = AssistantService(
        ark_client=ArkClient(settings),
        tool_handler=tool_handler,
        knowledge_store=knowledge_store,
        knowledge_context_max_chars=settings.knowledge_context_max_chars,
    )
    tts_service = TTSService(settings)
    asr_service = ASRService(settings)
    logger.info("TTS enabled: %s", tts_service.enabled)
    logger.info("ASR enabled: %s", asr_service.enabled)
    logger.info("Knowledge file: %s", knowledge_store.path)

    knowledge_tcp_server = None
    if settings.knowledge_http_port > 0:
        if not settings.knowledge_ingest_token:
            logger.warning(
                "KNOWLEDGE_HTTP_PORT=%s but KNOWLEDGE_INGEST_TOKEN is empty; HTTP ingest disabled.",
                settings.knowledge_http_port,
            )
        else:
            knowledge_tcp_server = await start_knowledge_http_server(
                settings.host,
                settings.knowledge_http_port,
                knowledge_store,
                settings.knowledge_ingest_token,
            )

    async def _serve_knowledge_http(server) -> None:
        """在独立任务中持有 asyncio.Server，使监听协程持续运行。"""
        async with server:
            await asyncio.Future()

    if knowledge_tcp_server is not None:
        asyncio.create_task(_serve_knowledge_http(knowledge_tcp_server))

    async with websockets.serve(
        lambda ws: handle_client(ws, settings, assistant, tts_service, asr_service),
        settings.host,
        settings.port,
    ):
        logger.info("WebSocket server is running on ws://%s:%s", settings.host, settings.port)
        if settings.knowledge_http_port > 0 and settings.knowledge_ingest_token:
            logger.info(
                "Knowledge ingest URL: http://%s:%s/v1/knowledge/ingest",
                settings.host,
                settings.knowledge_http_port,
            )
        await asyncio.Future()
