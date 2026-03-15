"""Project configuration utilities."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Settings:
    """Runtime settings loaded from environment variables."""

    host: str
    port: int
    debug: bool
    ws_token: str
    ark_base_url: str
    ark_api_key: str
    ark_model: str
    temperature_default: float
    temperature_factual: float
    temperature_chat: float
    netease_api_url: str
    netease_cookie: str
    netease_user_id: str
    netease_favorite_playlist_id: str
    request_timeout_seconds: int
    qweather_api_key: str
    qweather_geo_base_url: str
    qweather_weather_base_url: str
    tts_voice: str
    tts_rate: str
    tts_volume: str
    log_level: str
    asr_base_url: str
    asr_api_key: str
    asr_model: str
    asr_language: str
    asr_max_audio_bytes: int


def _to_bool(value: str) -> bool:
    """Convert string values like 'true'/'false' into booleans."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    """Load settings from .env and process them into typed fields."""
    # Load .env file into process environment variables if it exists.
    load_dotenv()

    # Read each field with a sensible fallback for local development.
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8765"))
    debug = _to_bool(os.getenv("DEBUG", "true"))
    ws_token = os.getenv("WS_TOKEN", "")
    ark_base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ark_api_key = os.getenv("ARK_API_KEY", "")
    ark_model = os.getenv("ARK_MODEL", "doubao-pro-32k")
    temperature_default = float(os.getenv("TEMPERATURE_DEFAULT", "0.6"))
    temperature_factual = float(os.getenv("TEMPERATURE_FACTUAL", "0.2"))
    temperature_chat = float(os.getenv("TEMPERATURE_CHAT", "0.9"))
    netease_api_url = os.getenv("NETEASE_API_URL", "http://127.0.0.1:3000")
    netease_cookie = os.getenv("NETEASE_COOKIE", "")
    netease_user_id = os.getenv("NETEASE_USER_ID", "")
    netease_favorite_playlist_id = os.getenv("NETEASE_FAVORITE_PLAYLIST_ID", "")
    request_timeout_seconds = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
    qweather_api_key = os.getenv("QWEATHER_API_KEY", "")
    qweather_geo_base_url = os.getenv("QWEATHER_GEO_BASE_URL", "https://geoapi.qweather.com/v2")
    qweather_weather_base_url = os.getenv("QWEATHER_WEATHER_BASE_URL", "https://devapi.qweather.com/v7")
    tts_voice = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    tts_rate = os.getenv("TTS_RATE", "+0%")
    tts_volume = os.getenv("TTS_VOLUME", "+0%")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    asr_base_url = os.getenv("ASR_BASE_URL", "https://api.openai.com/v1/audio/transcriptions")
    asr_api_key = os.getenv("ASR_API_KEY", "")
    asr_model = os.getenv("ASR_MODEL", "whisper-1")
    asr_language = os.getenv("ASR_LANGUAGE", "zh")
    asr_max_audio_bytes = int(os.getenv("ASR_MAX_AUDIO_BYTES", "10485760"))
    return Settings(
        host=host,
        port=port,
        debug=debug,
        ws_token=ws_token,
        ark_base_url=ark_base_url,
        ark_api_key=ark_api_key,
        ark_model=ark_model,
        temperature_default=temperature_default,
        temperature_factual=temperature_factual,
        temperature_chat=temperature_chat,
        netease_api_url=netease_api_url,
        netease_cookie=netease_cookie,
        netease_user_id=netease_user_id,
        netease_favorite_playlist_id=netease_favorite_playlist_id,
        request_timeout_seconds=request_timeout_seconds,
        qweather_api_key=qweather_api_key,
        qweather_geo_base_url=qweather_geo_base_url,
        qweather_weather_base_url=qweather_weather_base_url,
        tts_voice=tts_voice,
        tts_rate=tts_rate,
        tts_volume=tts_volume,
        log_level=log_level,
        asr_base_url=asr_base_url,
        asr_api_key=asr_api_key,
        asr_model=asr_model,
        asr_language=asr_language,
        asr_max_audio_bytes=asr_max_audio_bytes,
    )


def validate_settings(settings: Settings) -> list[str]:
    """Validate settings and return human-readable warnings/errors."""
    issues: list[str] = []
    if settings.port <= 0 or settings.port > 65535:
        issues.append("PORT must be in range 1-65535.")
    if settings.request_timeout_seconds <= 0:
        issues.append("REQUEST_TIMEOUT_SECONDS must be greater than 0.")
    if settings.temperature_factual < 0 or settings.temperature_chat < 0 or settings.temperature_default < 0:
        issues.append("Temperature values must be non-negative.")
    if settings.asr_max_audio_bytes <= 0:
        issues.append("ASR_MAX_AUDIO_BYTES must be greater than 0.")
    return issues
