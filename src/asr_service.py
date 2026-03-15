"""ASR service wrapper for audio-input websocket events."""

from __future__ import annotations

import asyncio
import json
import uuid
from urllib import error, request

from src.config import Settings


class ASRService:
    """Transcribe audio bytes into text with OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.asr_base_url
        self._api_key = settings.asr_api_key
        self._model = settings.asr_model
        self._language = settings.asr_language
        self._max_audio_bytes = settings.asr_max_audio_bytes

    @property
    def enabled(self) -> bool:
        """Whether ASR API is configured."""
        return bool(self._api_key)

    @property
    def max_audio_bytes(self) -> int:
        """Maximum accepted in-memory audio bytes per websocket request."""
        return self._max_audio_bytes

    def _build_multipart_body(self, audio_bytes: bytes, filename: str) -> tuple[bytes, str]:
        """Build multipart/form-data payload for transcription request."""
        boundary = f"----ai-assistant-{uuid.uuid4().hex}"
        parts: list[bytes] = []
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(audio_bytes)
        parts.append(b"\r\n")

        for key, value in (("model", self._model), ("language", self._language)):
            parts.append(f"--{boundary}\r\n".encode("utf-8"))
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            parts.append(str(value).encode("utf-8"))
            parts.append(b"\r\n")

        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(parts), boundary

    def _transcribe_sync(self, audio_bytes: bytes) -> dict[str, str | bool]:
        """Run HTTP request to ASR endpoint in blocking context."""
        body, boundary = self._build_multipart_body(audio_bytes=audio_bytes, filename="audio_input.wav")
        req = request.Request(
            self._base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return {"ok": False, "error": f"ASR HTTP error: {exc.code}"}
        except error.URLError as exc:
            return {"ok": False, "error": f"ASR connection error: {exc.reason}"}
        except json.JSONDecodeError:
            return {"ok": False, "error": "ASR response is not valid JSON"}
        text = str(data.get("text", "")).strip()
        if not text:
            return {"ok": False, "error": "ASR returned empty text"}
        return {"ok": True, "text": text}

    async def transcribe(self, audio_bytes: bytes) -> dict[str, str | bool]:
        """Transcribe audio asynchronously."""
        if not self.enabled:
            return {"ok": False, "error": "ASR is not configured (missing ASR_API_KEY)"}
        if not audio_bytes:
            return {"ok": False, "error": "Empty audio bytes"}
        if len(audio_bytes) > self._max_audio_bytes:
            return {"ok": False, "error": f"Audio too large (> {self._max_audio_bytes} bytes)"}
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)
