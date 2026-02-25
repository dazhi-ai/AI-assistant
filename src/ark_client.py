"""Minimal Ark (Doubao) OpenAI-compatible client."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from src.config import Settings


class ArkClient:
    """Call Ark chat completion API and expose tool-calling results."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ark_base_url.rstrip("/")
        self._api_key = settings.ark_api_key
        self._model = settings.ark_model
        self._default_temperature = settings.temperature_default
        self._factual_temperature = settings.temperature_factual
        self._chat_temperature = settings.temperature_chat

    @property
    def enabled(self) -> bool:
        """Return whether the remote model API is configured."""
        return bool(self._api_key)

    def _choose_temperature(self, user_text: str) -> float:
        """Tune temperature by intent category to balance accuracy and creativity."""
        lower_text = user_text.lower()
        factual_keywords = ("天气", "weather", "多少", "几点", "查询")
        chat_keywords = ("造型", "聊天", "开玩笑", "style")
        if any(keyword in lower_text for keyword in factual_keywords):
            return self._factual_temperature
        if any(keyword in lower_text for keyword in chat_keywords):
            return self._chat_temperature
        return self._default_temperature

    def chat_with_tools(
        self,
        user_text: str,
        tools: list[dict[str, Any]],
        system_prompt: str,
    ) -> dict[str, Any]:
        """Call model API and return assistant content and tool_calls."""
        if not self.enabled:
            return {"content": "", "tool_calls": []}

        endpoint = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "temperature": self._choose_temperature(user_text),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(f"Ark API HTTP error: {exc.code}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Ark API connection error: {exc.reason}") from exc

        choices = body.get("choices", [])
        if not choices:
            return {"content": "", "tool_calls": []}
        message = choices[0].get("message", {})
        return {
            "content": message.get("content", "") or "",
            "tool_calls": message.get("tool_calls", []) or [],
        }
