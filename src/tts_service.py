"""TTS service wrapper for streaming audio chunks."""

from __future__ import annotations

import base64
from typing import AsyncGenerator

from src.config import Settings

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None


class TTSService:
    """Generate audio chunks from text using Edge TTS."""

    def __init__(self, settings: Settings) -> None:
        self._voice = settings.tts_voice
        self._rate = settings.tts_rate
        self._volume = settings.tts_volume

    @property
    def enabled(self) -> bool:
        """Whether runtime has edge-tts available."""
        return edge_tts is not None

    async def stream_audio_chunks(self, text: str) -> AsyncGenerator[str, None]:
        """Yield base64-encoded audio chunks for websocket transport."""
        if not text:
            return
        if not self.enabled:
            return
        communicator = edge_tts.Communicate(text=text, voice=self._voice, rate=self._rate, volume=self._volume)
        async for chunk in communicator.stream():
            if chunk.get("type") != "audio":
                continue
            audio_data = chunk.get("data", b"")
            if not audio_data:
                continue
            yield base64.b64encode(audio_data).decode("ascii")
