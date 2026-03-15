"""ASR service wrapper for audio-input websocket events."""

from __future__ import annotations

import asyncio
import json
import uuid
from urllib import error, request

from src.config import Settings


class ASRService:
    """Transcribe audio bytes with provider-specific API."""

    def __init__(self, settings: Settings) -> None:
        self._provider = settings.asr_provider
        self._base_url = settings.asr_base_url
        self._api_key = settings.asr_api_key
        self._app_id = settings.asr_app_id or settings.volc_app_id
        self._access_token = settings.asr_access_token or settings.volc_access_token
        self._secret_key = settings.asr_secret_key or settings.volc_secret_key
        self._auth_style = settings.asr_auth_style
        self._model = settings.asr_model
        self._language = settings.asr_language
        self._max_audio_bytes = settings.asr_max_audio_bytes

    @property
    def enabled(self) -> bool:
        """Whether ASR API is configured."""
        if self._provider == "openai":
            return bool(self._api_key and self._base_url)
        if self._provider == "volc":
            return bool(self._base_url and self._app_id and self._access_token)
        return False

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

    def _extract_text(self, data: dict) -> str:
        """Extract text from a few common ASR response formats."""
        direct_text = str(data.get("text", "")).strip()
        if direct_text:
            return direct_text
        result = data.get("result")
        if isinstance(result, dict):
            nested_text = str(result.get("text", "")).strip()
            if nested_text:
                return nested_text
            utterances = result.get("utterances", [])
            if isinstance(utterances, list):
                pieces = [str(item.get("text", "")).strip() for item in utterances if isinstance(item, dict)]
                joined = " ".join([piece for piece in pieces if piece])
                if joined:
                    return joined
        utterances = data.get("utterances", [])
        if isinstance(utterances, list):
            pieces = [str(item.get("text", "")).strip() for item in utterances if isinstance(item, dict)]
            return " ".join([piece for piece in pieces if piece]).strip()
        return ""

    def _build_headers(self, boundary: str) -> dict[str, str]:
        """Build request headers based on provider."""
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self._provider == "openai":
            headers["Authorization"] = f"Bearer {self._api_key}"
            return headers
        token = self._access_token
        if self._auth_style == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif self._auth_style == "bearer_semicolon":
            headers["Authorization"] = f"Bearer; {token}"
        else:
            # Volc token mode typically uses "Bearer; {token}".
            headers["Authorization"] = f"Bearer; {token}"
        if self._app_id:
            headers["X-Appid"] = self._app_id
        return headers

    def _transcribe_sync(self, audio_bytes: bytes) -> dict[str, str | bool]:
        """Run HTTP request to ASR endpoint in blocking context."""
        body, boundary = self._build_multipart_body(audio_bytes=audio_bytes, filename="audio_input.wav")
        req = request.Request(
            self._base_url,
            data=body,
            headers=self._build_headers(boundary),
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
        text = self._extract_text(data)
        if not text:
            return {"ok": False, "error": "ASR returned empty text"}
        return {"ok": True, "text": text}

    async def transcribe(self, audio_bytes: bytes) -> dict[str, str | bool]:
        """Transcribe audio asynchronously."""
        if not self.enabled:
            if self._provider == "volc":
                return {
                    "ok": False,
                    "error": "ASR is not configured for volc mode (check ASR_BASE_URL and ASR_ACCESS_TOKEN/ASR_APP_ID).",
                }
            return {"ok": False, "error": "ASR is not configured (missing ASR_API_KEY)."}
        if not audio_bytes:
            return {"ok": False, "error": "Empty audio bytes"}
        if len(audio_bytes) > self._max_audio_bytes:
            return {"ok": False, "error": f"Audio too large (> {self._max_audio_bytes} bytes)"}
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)
