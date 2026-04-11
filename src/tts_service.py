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
        self._volc_auth_style = settings.tts_volc_auth_style
        self._volc_tts_resource_id = (settings.volc_tts_resource_id or "").strip()
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        """Whether runtime has edge-tts available."""
        if self._provider == "edge":
            return edge_tts is not None
        if self._provider == "volc":
            return bool((self._volc_base_url or self._volc_ws_url) and self._volc_app_id and self._volc_access_token)
        return False

    @property
    def last_error(self) -> str:
        """Last human-readable TTS error for observability."""
        return self._last_error

    def _set_error(self, message: str) -> None:
        """Persist latest TTS error so caller can return it to client."""
        self._last_error = message.strip()

    def _clear_error(self) -> None:
        """Clear last error before each synthesis task."""
        self._last_error = ""

    def _build_volc_auth_header(self) -> str:
        """Build volc Authorization header based on configured style."""
        token = self._volc_access_token.strip()
        if not token:
            return ""
        if self._volc_auth_style == "bearer":
            return f"Bearer {token}"
        # Volc default token mode commonly expects "Bearer; token".
        return f"Bearer; {token}"

    def _resolve_volc_http_url(self) -> str:
        """Resolve volc HTTP endpoint, tolerating ws-style URLs in config."""
        v3_uni = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        base_url = (self._volc_base_url or "").strip()
        if base_url:
            if base_url.startswith("ws://") or base_url.startswith("wss://"):
                scheme = "https://" if base_url.startswith("wss://") else "http://"
                host_path = base_url.split("://", 1)[1]
                if host_path.endswith("/api/v3/tts/bidirection"):
                    host_path = host_path.replace(
                        "/api/v3/tts/bidirection", "/api/v3/tts/unidirectional"
                    )
                return f"{scheme}{host_path}"
            return base_url
        ws_url = (self._volc_ws_url or "").strip()
        if "openspeech.bytedance.com" in ws_url:
            return v3_uni
        return ""

    @staticmethod
    def _is_volc_openspeech_v3_http(http_url: str) -> bool:
        return "openspeech.bytedance.com" in http_url and "/api/v3/tts/unidirectional" in http_url

    def _mask_secret(self, secret_text: str) -> str:
        """Mask secret values for safe startup logging."""
        value = secret_text.strip()
        if not value:
            return ""
        if len(value) <= 6:
            return "***"
        return f"{value[:3]}***{value[-3:]}"

    def startup_self_check(self) -> dict[str, object]:
        """Return startup diagnostics for fast TTS configuration verification."""
        check: dict[str, object] = {
            "provider": self._provider,
            "enabled": self.enabled,
            "issues": [],
        }
        issues: list[str] = []

        if self._provider == "edge":
            check["voice"] = self._voice
            check["rate"] = self._rate
            check["volume"] = self._volume
            check["edge_runtime_ready"] = edge_tts is not None
            if edge_tts is None:
                issues.append("edge-tts is not installed in current runtime.")
            check["issues"] = issues
            return check

        if self._provider == "volc":
            resolved_http_url = self._resolve_volc_http_url()
            check["volc_http_url"] = resolved_http_url
            check["volc_ws_url"] = (self._volc_ws_url or "").strip()
            check["volc_tts_resource_id"] = self._volc_tts_resource_id
            check["voice_type"] = self._volc_voice_type
            check["cluster"] = self._volc_cluster
            check["encoding"] = self._volc_encoding
            check["auth_style"] = self._volc_auth_style
            check["app_id_masked"] = self._mask_secret(self._volc_app_id)
            check["access_token_masked"] = self._mask_secret(self._volc_access_token)
            if not self._volc_app_id.strip():
                issues.append("VOLC_APP_ID is empty.")
            if not self._volc_access_token.strip():
                issues.append("VOLC_ACCESS_TOKEN is empty.")
            if not resolved_http_url:
                issues.append("No HTTP TTS endpoint resolved from TTS_VOLC_BASE_URL/VOLC_TTS_WS_URL.")
            elif not (resolved_http_url.startswith("http://") or resolved_http_url.startswith("https://")):
                issues.append("Resolved TTS endpoint is not a valid HTTP URL.")
            if not self._volc_voice_type.strip():
                issues.append("TTS_VOLC_VOICE_TYPE is empty.")
            if self._volc_encoding != "mp3":
                issues.append(
                    "TTS_VOLC_ENCODING is not mp3; current web-client expects audio/mpeg for stable playback."
                )
            check["issues"] = issues
            return check

        issues.append(f"Unsupported TTS_PROVIDER: {self._provider}")
        check["issues"] = issues
        return check

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

    def _build_volc_v3_unidirectional_payload(self, text: str) -> bytes:
        """Body for openspeech HTTP Chunked V3 unidirectional (matches X-Api-Resource-Id billing)."""
        fmt = self._volc_encoding if self._volc_encoding in {"mp3", "ogg_opus", "pcm", "wav"} else "mp3"
        speech = int(round((self._volc_speed_ratio - 1.0) * 50))
        speech = max(-50, min(100, speech))
        loud = int(round((self._volc_volume_ratio - 1.0) * 50))
        loud = max(-50, min(100, loud))
        audio_params: dict[str, object] = {
            "format": fmt,
            "speech_rate": speech,
            "loudness_rate": loud,
        }
        payload = {
            "user": {"uid": "ai-assistant"},
            "req_params": {
                "text": text,
                "speaker": self._volc_voice_type.strip(),
                "audio_params": audio_params,
            },
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _extract_volc_v3_audio(self, raw_bytes: bytes, content_type: str) -> bytes:
        """Parse V3 unidirectional JSON body (single object or newline-delimited chunks with base64 audio)."""
        if "audio" in content_type and "json" not in content_type:
            return raw_bytes
        text = raw_bytes.decode("utf-8", errors="ignore").strip()
        if not text:
            raise ValueError("empty V3 TTS response body")
        pieces: list[bytes] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = obj.get("code")
            if code not in (None, 0, "0") and not str(obj.get("data", "")).strip():
                msg = obj.get("message") or obj
                raise ValueError(f"V3 TTS error: {msg}")
            b64 = str(obj.get("data", "") or "").strip()
            if not b64 and isinstance(obj.get("result"), dict):
                b64 = str(obj["result"].get("audio", "") or "").strip()
            if b64:
                pieces.append(base64.b64decode(b64))
        if pieces:
            return b"".join(pieces)
        obj = json.loads(text)
        b64 = str(obj.get("data", "") or "").strip()
        if not b64 and isinstance(obj.get("result"), dict):
            b64 = str(obj["result"].get("audio", "") or "").strip()
        if not b64:
            raise ValueError(f"Missing audio in V3 TTS response: {str(obj)[:500]}")
        return base64.b64decode(b64)

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
        http_url = self._resolve_volc_http_url()
        if not http_url:
            self._set_error("TTS_VOLC_BASE_URL is empty and no fallback HTTP endpoint is available.")
            return

        use_v3 = self._is_volc_openspeech_v3_http(http_url)
        payload_bytes = (
            self._build_volc_v3_unidirectional_payload(text)
            if use_v3
            else self._build_volc_payload(text)
        )

        def _request_sync() -> tuple[bool, str, bytes] | None:
            if not http_url:
                return None
            auth_header = self._build_volc_auth_header()
            headers = {"Content-Type": "application/json"}
            if auth_header:
                headers["Authorization"] = auth_header
            if use_v3 and self._volc_app_id.strip() and self._volc_access_token.strip():
                headers["X-Api-App-Id"] = self._volc_app_id.strip()
                headers["X-Api-Access-Key"] = self._volc_access_token.strip()
                if self._volc_tts_resource_id:
                    headers["X-Api-Resource-Id"] = self._volc_tts_resource_id
                headers["X-Api-Connect-Id"] = str(uuid.uuid4())
            req = request.Request(
                http_url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=45) as response:
                    content_type = response.headers.get("Content-Type", "").lower()
                    body = response.read()
                    return True, content_type, body
            except error.HTTPError as exc:
                err_body = b""
                try:
                    err_body = exc.read()
                except Exception:  # noqa: BLE001
                    err_body = b""
                return False, "application/json", err_body or str(exc).encode("utf-8")
            except error.URLError as exc:
                return False, "text/plain", str(exc.reason).encode("utf-8")

        result = await asyncio.to_thread(_request_sync)
        if result is None:
            self._set_error("TTS request was not sent because endpoint is empty.")
            return
        ok, content_type, body = result
        if not ok:
            message = body.decode("utf-8", errors="ignore").strip()
            if not message:
                message = "unknown volc tts request error"
            self._set_error(f"Volc TTS HTTP request failed: {message}")
            return
        try:
            if use_v3:
                audio_bytes = self._extract_volc_v3_audio(body, content_type)
            else:
                audio_bytes = self._extract_volc_audio(raw_bytes=body, content_type=content_type)
        except (ValueError, json.JSONDecodeError) as exc:
            self._set_error(f"Volc TTS parse error: {exc}")
            return
        if not audio_bytes:
            self._set_error("Volc TTS returned empty audio bytes.")
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
            auth_header = self._build_volc_auth_header()
            async with websockets.connect(
                ws_url,
                additional_headers={"Authorization": auth_header} if auth_header else None,
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
                        self._set_error(f"Volc TTS WS error: {data.get('error')}")
                        break
                    if data.get("is_end") or data.get("done"):
                        break
                    audio_base64 = str(data.get("data", "")).strip()
                    if not audio_base64 and isinstance(data.get("result"), dict):
                        audio_base64 = str(data["result"].get("audio", "")).strip()
                    if audio_base64:
                        yield audio_base64
        except Exception as exc:  # noqa: BLE001
            self._set_error(f"Volc TTS WS connection error: {exc}")
            return

    async def stream_audio_chunks(self, text: str) -> AsyncGenerator[str, None]:
        """Yield base64-encoded audio chunks for websocket transport."""
        self._clear_error()
        if not text:
            self._set_error("TTS input text is empty.")
            return
        if not self.enabled:
            self._set_error("TTS is not enabled with current provider configuration.")
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
