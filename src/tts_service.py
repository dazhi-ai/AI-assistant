"""TTS service wrapper for streaming audio chunks."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import AsyncGenerator
from urllib import error, request

import websockets

from src.config import Settings

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None


class TTSService:
    """Generate audio chunks from text using provider-specific TTS."""

    def __init__(self, settings: Settings) -> None:
        self._provider = settings.tts_provider
        self._voice = settings.tts_voice
        self._rate = settings.tts_rate
        self._volume = settings.tts_volume
        self._volc_base_url = settings.tts_volc_base_url
        self._volc_ws_url = settings.volc_tts_ws_url
        self._volc_app_id = settings.volc_app_id
        self._volc_access_token = settings.volc_access_token
        self._volc_cluster = settings.tts_volc_cluster
        self._volc_voice_type = settings.tts_volc_voice_type
        self._volc_encoding = settings.tts_volc_encoding
        self._volc_speed_ratio = settings.tts_volc_speed_ratio
        self._volc_volume_ratio = settings.tts_volc_volume_ratio
        self._volc_pitch_ratio = settings.tts_volc_pitch_ratio

    @property
    def enabled(self) -> bool:
        """Whether runtime has edge-tts available."""
        if self._provider == "edge":
            return edge_tts is not None
        if self._provider == "volc":
            return bool((self._volc_base_url or self._volc_ws_url) and self._volc_app_id and self._volc_access_token)
        return False

    def _build_volc_payload(self, text: str) -> bytes:
        """Build volc tts request payload using common V3 structure."""
        payload = {
            "app": {
                "appid": self._volc_app_id,
                "token": self._volc_access_token,
                "cluster": self._volc_cluster,
            },
            "user": {"uid": "ai-assistant"},
            "audio": {
                "voice_type": self._volc_voice_type,
                "encoding": self._volc_encoding,
                "speed_ratio": self._volc_speed_ratio,
                "volume_ratio": self._volc_volume_ratio,
                "pitch_ratio": self._volc_pitch_ratio,
            },
            "request": {
                "reqid": uuid.uuid4().hex,
                "text": text,
                "text_type": "plain",
                "operation": "query",
            },
        }
        return json.dumps(payload).encode("utf-8")

    def _extract_volc_audio(self, raw_bytes: bytes, content_type: str) -> bytes:
        """Normalize volc response body to raw audio bytes."""
        if "application/json" not in content_type:
            return raw_bytes
        data = json.loads(raw_bytes.decode("utf-8"))
        audio_base64 = str(data.get("data", "")).strip()
        if not audio_base64 and isinstance(data.get("result"), dict):
            audio_base64 = str(data["result"].get("audio", "")).strip()
        if not audio_base64:
            raise ValueError(f"Missing audio data in volc response: {data}")
        return base64.b64decode(audio_base64)

    async def _stream_volc_chunks(self, text: str) -> AsyncGenerator[str, None]:
        """Call volc HTTP API once and split audio bytes into websocket chunks."""
        ws_url = self._volc_base_url or self._volc_ws_url
        if ws_url.startswith("ws://") or ws_url.startswith("wss://"):
            async for ws_chunk in self._stream_volc_ws_chunks(text):
                yield ws_chunk
            return

        def _request_sync() -> tuple[str, bytes] | None:
            if not self._volc_base_url:
                return None
            req = request.Request(
                self._volc_base_url,
                data=self._build_volc_payload(text),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer; {self._volc_access_token}",
                },
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=45) as response:
                    content_type = response.headers.get("Content-Type", "").lower()
                    body = response.read()
                    return content_type, body
            except error.HTTPError:
                return None
            except error.URLError:
                return None

        result = await asyncio.to_thread(_request_sync)
        if result is None:
            return
        content_type, body = result
        try:
            audio_bytes = self._extract_volc_audio(raw_bytes=body, content_type=content_type)
        except (ValueError, json.JSONDecodeError):
            return
        if not audio_bytes:
            return
        chunk_size = 24 * 1024
        offset = 0
        while offset < len(audio_bytes):
            chunk = audio_bytes[offset : offset + chunk_size]
            offset += chunk_size
            yield base64.b64encode(chunk).decode("ascii")

    async def _stream_volc_ws_chunks(self, text: str) -> AsyncGenerator[str, None]:
        """Best-effort websocket integration for volc bidirectional TTS."""
        ws_url = self._volc_base_url or self._volc_ws_url
        if not ws_url:
            return
        payload = self._build_volc_payload(text).decode("utf-8")
        try:
            async with websockets.connect(
                ws_url,
                additional_headers={"Authorization": f"Bearer; {self._volc_access_token}"},
                open_timeout=10,
            ) as websocket:
                await websocket.send(payload)
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=6)
                    except TimeoutError:
                        break
                    if isinstance(message, bytes):
                        if message:
                            yield base64.b64encode(message).decode("ascii")
                        continue
                    message_text = str(message).strip()
                    if not message_text:
                        continue
                    try:
                        data = json.loads(message_text)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        break
                    if data.get("is_end") or data.get("done"):
                        break
                    audio_base64 = str(data.get("data", "")).strip()
                    if not audio_base64 and isinstance(data.get("result"), dict):
                        audio_base64 = str(data["result"].get("audio", "")).strip()
                    if audio_base64:
                        yield audio_base64
        except Exception:  # noqa: BLE001
            return

    async def stream_audio_chunks(self, text: str) -> AsyncGenerator[str, None]:
        """Yield base64-encoded audio chunks for websocket transport."""
        if not text:
            return
        if not self.enabled:
            return
        if self._provider == "edge":
            communicator = edge_tts.Communicate(text=text, voice=self._voice, rate=self._rate, volume=self._volume)
            async for chunk in communicator.stream():
                if chunk.get("type") != "audio":
                    continue
                audio_data = chunk.get("data", b"")
                if not audio_data:
                    continue
                yield base64.b64encode(audio_data).decode("ascii")
            return
        async for volc_chunk in self._stream_volc_chunks(text):
            yield volc_chunk
