"""ASR service wrapper for audio-input websocket events."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from urllib import error, request

from src.config import Settings

# 火山引擎 REST ASR（非流式）使用的 cluster 名称
_VOLC_ASR_REST_CLUSTER = "volcengine_input_common"

# 火山引擎 REST ASR 接口地址（v1 为 HTTP 同步接口，v2 为 WebSocket 流式接口）
_VOLC_ASR_REST_URL = "https://openspeech.bytedance.com/api/v1/asr"


class ASRService:
    """Transcribe audio bytes with provider-specific API."""

    def __init__(self, settings: Settings) -> None:
        self._provider = settings.asr_provider

        # 处理 ASR_BASE_URL：如果是 wss:// 流式地址，自动转换为 REST 地址
        raw_url = settings.asr_base_url
        if self._provider == "volc":
            if raw_url.startswith("wss://") or raw_url.startswith("ws://"):
                # 用户填了 WebSocket 流式地址，改用 REST 接口
                self._base_url = _VOLC_ASR_REST_URL
            else:
                self._base_url = raw_url or _VOLC_ASR_REST_URL
        else:
            self._base_url = raw_url

        self._api_key = settings.asr_api_key
        # ASR_APP_ID 优先，否则回退到公共 VOLC_APP_ID
        self._app_id = settings.asr_app_id or settings.volc_app_id
        # ASR_ACCESS_TOKEN 优先，否则回退到公共 VOLC_ACCESS_TOKEN
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

    # ------------------------------------------------------------------ #
    # 火山引擎 REST ASR：JSON + base64 音频体                             #
    # ------------------------------------------------------------------ #

    def _build_volc_json_body(self, audio_bytes: bytes) -> bytes:
        """
        构造火山引擎 REST ASR (v1) 请求体。

        接口文档格式：
        POST https://openspeech.bytedance.com/api/v1/asr
        Content-Type: application/json
        Authorization: Bearer; {access_token}
        X-Appid: {appid}

        Body:
        {
            "appid": "...",
            "token": "...",
            "cluster": "volcengine_input_common",
            "uid": "...",
            "audio": {
                "format": "wav",
                "data": "<base64>",
                "channel": 1,
                "bits": 16,
                "rate": 16000,
                "codec": "raw"
            },
            "request": {
                "reqid": "<uuid>",
                "nbest": 1,
                "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuation",
                "sequence": -1
            }
        }
        """
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "appid": self._app_id,
            "token": self._access_token,
            "cluster": _VOLC_ASR_REST_CLUSTER,
            "uid": "tablet_user",
            "audio": {
                "format": "wav",
                "data": audio_b64,
                "channel": 1,
                "bits": 16,
                "rate": 16000,
                "codec": "raw",
            },
            "request": {
                "reqid": uuid.uuid4().hex,
                "nbest": 1,
                "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuation",
                "sequence": -1,
            },
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # ------------------------------------------------------------------ #
    # OpenAI 兼容格式：multipart/form-data                                #
    # ------------------------------------------------------------------ #

    def _build_multipart_body(self, audio_bytes: bytes, filename: str) -> tuple[bytes, str]:
        """Build multipart/form-data payload for OpenAI-compatible transcription."""
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

    # ------------------------------------------------------------------ #
    # 响应文本提取                                                         #
    # ------------------------------------------------------------------ #

    def _extract_text(self, data: dict) -> str:
        """
        从多种 ASR 响应格式中提取识别文本。

        支持的格式：
        - OpenAI:       {"text": "..."}
        - 火山引擎 v1:  {"resp": {"utterances": [{"text": "..."}]}}
        - 火山引擎 nbest: {"resp": {"nbest": [{"transcript": "..."}]}}
        - 通用 fallback: {"result": {"text": "..."}} / {"utterances": [...]}
        """
        # OpenAI 格式
        direct_text = str(data.get("text", "")).strip()
        if direct_text:
            return direct_text

        # 火山引擎 v1 REST 格式：{"resp": {...}}
        resp = data.get("resp")
        if isinstance(resp, dict):
            utterances = resp.get("utterances", [])
            if isinstance(utterances, list):
                pieces = [
                    str(item.get("text", "")).strip()
                    for item in utterances
                    if isinstance(item, dict)
                ]
                joined = " ".join([p for p in pieces if p])
                if joined:
                    return joined
            # nbest 兜底
            nbest = resp.get("nbest", [])
            if isinstance(nbest, list) and nbest:
                first = nbest[0]
                if isinstance(first, dict):
                    transcript = str(first.get("transcript", "")).strip()
                    if transcript:
                        return transcript

        # 通用 {"result": {...}} 格式
        result = data.get("result")
        if isinstance(result, dict):
            nested = str(result.get("text", "")).strip()
            if nested:
                return nested
            utterances = result.get("utterances", [])
            if isinstance(utterances, list):
                pieces = [str(u.get("text", "")).strip() for u in utterances if isinstance(u, dict)]
                joined = " ".join([p for p in pieces if p])
                if joined:
                    return joined

        # 顶层 utterances 兜底
        utterances = data.get("utterances", [])
        if isinstance(utterances, list):
            pieces = [str(u.get("text", "")).strip() for u in utterances if isinstance(u, dict)]
            return " ".join([p for p in pieces if p]).strip()

        return ""

    # ------------------------------------------------------------------ #
    # 核心转写逻辑                                                         #
    # ------------------------------------------------------------------ #

    def _transcribe_sync(self, audio_bytes: bytes) -> dict[str, str | bool]:
        """Run HTTP request to ASR endpoint in blocking context."""
        if self._provider == "volc":
            # 火山引擎 REST API：JSON body
            body = self._build_volc_json_body(audio_bytes)
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                # 火山引擎鉴权格式：Bearer; {access_token}
                "Authorization": f"Bearer; {self._access_token}",
            }
            if self._app_id:
                headers["X-Appid"] = self._app_id
        else:
            # OpenAI 兼容：multipart/form-data
            body, boundary = self._build_multipart_body(
                audio_bytes=audio_bytes, filename="audio_input.wav"
            )
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer {self._api_key}",
            }

        req = request.Request(
            self._base_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8")[:300]
            except Exception:
                pass
            return {"ok": False, "error": f"ASR HTTP {exc.code}: {err_body}"}
        except error.URLError as exc:
            return {"ok": False, "error": f"ASR connection error: {exc.reason}"}
        except json.JSONDecodeError:
            return {"ok": False, "error": "ASR response is not valid JSON"}

        # 火山引擎 v1 REST 成功码为 1000
        if self._provider == "volc":
            code = data.get("code", 0)
            if code != 1000:
                msg = data.get("message", "unknown error")
                return {"ok": False, "error": f"ASR Volcengine code {code}: {msg}"}

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
                    "error": (
                        "ASR volc 未配置：请检查 VOLC_APP_ID / VOLC_ACCESS_TOKEN 和 ASR_BASE_URL。"
                    ),
                }
            return {"ok": False, "error": "ASR 未配置：缺少 ASR_API_KEY。"}
        if not audio_bytes:
            return {"ok": False, "error": "Empty audio bytes"}
        if len(audio_bytes) > self._max_audio_bytes:
            return {"ok": False, "error": f"Audio too large (> {self._max_audio_bytes} bytes)"}
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes)
