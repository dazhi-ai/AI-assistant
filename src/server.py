"""WebSocket gateway with auth, heartbeat, and tool orchestration."""

import asyncio
import logging
import re

import websockets
from websockets.asyncio.server import ServerConnection

from plugins.netease_cloud import NeteaseCloudController
from plugins.weather_service import WeatherService
from src.ark_client import ArkClient
from src.assistant_service import AssistantService
from src.config import Settings
from src.protocol import build_message, parse_message
from src.tool_handler import ToolHandler
from src.tts_service import TTSService


logger = logging.getLogger(__name__)


async def _send_message(websocket: ServerConnection, message_type: str, payload: dict, trace_id: str | None = None) -> None:
    """Send one protocol message to the client."""
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
    await _send_message(
        websocket,
        "AUDIO_END",
        {"total_chunks": chunk_index},
        trace_id=trace_id,
    )


async def handle_client(
    websocket: ServerConnection,
    settings: Settings,
    assistant: AssistantService,
    tts_service: TTSService,
) -> None:
    """Handle one client connection using protocol-based events."""
    logger.info("Client connected")
    session_id = str(id(websocket))
    authed = settings.ws_token == ""
    audio_input_chunk_count = 0
    try:
        async for raw_message in websocket:
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
                # Hardware path placeholder: chunk will feed ASR pipeline in next iteration.
                audio_input_chunk_count += 1
                continue

            if message.type == "AUDIO_INPUT_END":
                await _send_message(
                    websocket,
                    "TEXT",
                    {
                        "text": (
                            "已收到音频输入，但当前版本尚未接入实时 ASR。"
                            f"本次累计分片: {audio_input_chunk_count}"
                        )
                    },
                    trace_id=message.trace_id,
                )
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
                process_result = await assistant.process_user_text(session_id=session_id, user_text=user_text)
                await _send_message(
                    websocket,
                    "TEXT",
                    {"text": process_result["assistant_text"]},
                    trace_id=message.trace_id,
                )
                model_switch = _detect_model_switch(user_text)
                if model_switch:
                    await _send_message(
                        websocket,
                        "MODEL_SWITCH",
                        model_switch,
                        trace_id=message.trace_id,
                    )
                for tool_result in process_result["tool_results"]:
                    await _send_message(
                        websocket,
                        "TOOL_RESULT",
                        tool_result,
                        trace_id=message.trace_id,
                    )
                    if tool_result["name"] == "like_music" and tool_result["result"].get("ok"):
                        await _send_message(
                            websocket,
                            "EFFECT",
                            {"action": "HEART"},
                            trace_id=message.trace_id,
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
                            trace_id=message.trace_id,
                        )
                    if tool_result["name"] == "play_music" and tool_result["result"].get("ok"):
                        await _send_message(
                            websocket,
                            "AUDIO_URL",
                            {"url": tool_result["result"].get("url", "")},
                            trace_id=message.trace_id,
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
                            trace_id=message.trace_id,
                        )
                await _stream_tts_to_client(
                    websocket=websocket,
                    tts_service=tts_service,
                    text=process_result["assistant_text"],
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
    weather = WeatherService(
        api_key=settings.qweather_api_key,
        geo_base_url=settings.qweather_geo_base_url,
        weather_base_url=settings.qweather_weather_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
    tool_handler = ToolHandler(netease, weather)
    assistant = AssistantService(ark_client=ArkClient(settings), tool_handler=tool_handler)
    tts_service = TTSService(settings)
    logger.info("TTS enabled: %s", tts_service.enabled)
    async with websockets.serve(
        lambda ws: handle_client(ws, settings, assistant, tts_service),
        settings.host,
        settings.port,
    ):
        logger.info("WebSocket server is running on ws://%s:%s", settings.host, settings.port)
        await asyncio.Future()
