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
    qweather_api_host: str
    qweather_geo_base_url: str
    qweather_weather_base_url: str
    tts_voice: str
    tts_rate: str
    tts_volume: str
    tts_provider: str
    tts_volc_base_url: str
    tts_volc_voice_type: str
    tts_volc_cluster: str
    tts_volc_encoding: str
    tts_volc_speed_ratio: float
    tts_volc_volume_ratio: float
    tts_volc_pitch_ratio: float
    tts_volc_auth_style: str
    log_level: str
    volc_app_id: str
    volc_access_token: str
    volc_secret_key: str
    volc_asr_ws_url: str
    volc_tts_ws_url: str
    volc_asr_cluster: str
    asr_provider: str
    asr_base_url: str
    asr_api_key: str
    asr_app_id: str
    asr_access_token: str
    asr_secret_key: str
    asr_auth_style: str
    asr_model: str
    asr_language: str
    asr_max_audio_bytes: int
    # 知识库 HTTP 写入（供外部服务器定时推送）；端口为 0 时不启动 HTTP，仅可本地读写文件
    knowledge_http_port: int
    knowledge_ingest_token: str
    knowledge_data_path: str
    knowledge_context_max_chars: int
    # 小智镜像桥接：xiaozhi-esp32-server 用此 token 以 MIRROR_INIT 连入，将 AI 回复推送给平板
    mirror_token: str
    # 小智 MySQL 同步角色 prompt（含每日新闻）
    xiaozhi_mysql_host: str
    xiaozhi_mysql_port: int
    xiaozhi_mysql_user: str
    xiaozhi_mysql_password: str
    xiaozhi_mysql_db: str
    xiaozhi_agent_id: str
    xiaozhi_prompt_refresh_seconds: int


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
    qweather_api_host = os.getenv("QWEATHER_API_HOST", "").strip()
    qweather_geo_base_url = os.getenv("QWEATHER_GEO_BASE_URL", "https://geoapi.qweather.com/v2")
    qweather_weather_base_url = os.getenv("QWEATHER_WEATHER_BASE_URL", "https://devapi.qweather.com/v7")
    tts_voice = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    tts_rate = os.getenv("TTS_RATE", "+0%")
    tts_volume = os.getenv("TTS_VOLUME", "+0%")
    tts_provider_raw = os.getenv("TTS_PROVIDER", "edge").strip().lower()
    tts_provider = "volc" if tts_provider_raw in {"volcengine", "volc"} else tts_provider_raw
    tts_volc_base_url = os.getenv("TTS_VOLC_BASE_URL", "")
    tts_volc_voice_type = os.getenv("TTS_VOLC_VOICE_TYPE", "BV001_streaming")
    tts_volc_cluster = os.getenv("TTS_VOLC_CLUSTER", "volcano_tts")
    tts_volc_encoding = os.getenv("TTS_VOLC_ENCODING", "mp3")
    tts_volc_speed_ratio = float(os.getenv("TTS_VOLC_SPEED_RATIO", "1.0"))
    tts_volc_volume_ratio = float(os.getenv("TTS_VOLC_VOLUME_RATIO", "1.0"))
    tts_volc_pitch_ratio = float(os.getenv("TTS_VOLC_PITCH_RATIO", "1.0"))
    tts_volc_auth_style_raw = os.getenv("TTS_VOLC_AUTH_STYLE", "auto").strip().lower()
    tts_volc_auth_style = "bearer_semicolon" if tts_volc_auth_style_raw in {"auto", "token"} else tts_volc_auth_style_raw
    log_level = os.getenv("LOG_LEVEL", "INFO")
    volc_app_id = os.getenv("VOLC_APP_ID", "")
    volc_access_token = os.getenv("VOLC_ACCESS_TOKEN", "")
    volc_secret_key = os.getenv("VOLC_SECRET_KEY", "")
    volc_asr_ws_url = os.getenv("VOLC_ASR_WS_URL", "wss://openspeech.bytedance.com/api/v2/asr")
    volc_tts_ws_url = os.getenv("VOLC_TTS_WS_URL", "wss://openspeech.bytedance.com/api/v3/tts/bidirection")
    # 与 xiaozhi DoubaoStreamASR 一致；若控制台仅开通「流式」未开通「一句话」则必须用 streaming_common
    volc_asr_cluster = os.getenv("VOLC_ASR_CLUSTER", "volcengine_streaming_common").strip()
    asr_provider_raw = os.getenv("ASR_PROVIDER", "openai").strip().lower()
    asr_provider = "volc" if asr_provider_raw in {"volcengine", "volc"} else asr_provider_raw
    asr_base_url = os.getenv("ASR_BASE_URL", "https://api.openai.com/v1/audio/transcriptions")
    asr_api_key = os.getenv("ASR_API_KEY", "")
    asr_app_id = os.getenv("ASR_APP_ID", "")
    asr_access_token = os.getenv("ASR_ACCESS_TOKEN", "")
    asr_secret_key = os.getenv("ASR_SECRET_KEY", "")
    asr_auth_style_raw = os.getenv("ASR_AUTH_STYLE", "auto").strip().lower()
    asr_auth_style = "bearer_semicolon" if asr_auth_style_raw == "token" else asr_auth_style_raw
    if asr_provider == "volc" and asr_base_url.strip().lower() == "auto":
        asr_base_url = "https://openspeech.bytedance.com/api/v2/asr"
    asr_model = os.getenv("ASR_MODEL", "whisper-1")
    asr_language = os.getenv("ASR_LANGUAGE", "zh")
    asr_max_audio_bytes = int(os.getenv("ASR_MAX_AUDIO_BYTES", "10485760"))
    knowledge_http_port = int(os.getenv("KNOWLEDGE_HTTP_PORT", "0"))
    knowledge_ingest_token = os.getenv("KNOWLEDGE_INGEST_TOKEN", "").strip()
    knowledge_data_path = os.getenv("KNOWLEDGE_DATA_PATH", "data/knowledge_base.jsonl").strip()
    knowledge_context_max_chars = int(os.getenv("KNOWLEDGE_CONTEXT_MAX_CHARS", "6000"))
    mirror_token = os.getenv("MIRROR_TOKEN", "").strip()
    xiaozhi_mysql_host = os.getenv("XIAOZHI_MYSQL_HOST", "172.19.0.2").strip()
    xiaozhi_mysql_port = int(os.getenv("XIAOZHI_MYSQL_PORT", "3306"))
    xiaozhi_mysql_user = os.getenv("XIAOZHI_MYSQL_USER", "root").strip()
    xiaozhi_mysql_password = os.getenv("XIAOZHI_MYSQL_PASSWORD", "").strip()
    xiaozhi_mysql_db = os.getenv("XIAOZHI_MYSQL_DB", "xiaozhi_esp32_server").strip()
    xiaozhi_agent_id = os.getenv("XIAOZHI_AGENT_ID", "").strip()
    xiaozhi_prompt_refresh_seconds = int(os.getenv("XIAOZHI_PROMPT_REFRESH_SECONDS", "600"))
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
        qweather_api_host=qweather_api_host,
        qweather_geo_base_url=qweather_geo_base_url,
        qweather_weather_base_url=qweather_weather_base_url,
        tts_voice=tts_voice,
        tts_rate=tts_rate,
        tts_volume=tts_volume,
        tts_provider=tts_provider,
        tts_volc_base_url=tts_volc_base_url,
        tts_volc_voice_type=tts_volc_voice_type,
        tts_volc_cluster=tts_volc_cluster,
        tts_volc_encoding=tts_volc_encoding,
        tts_volc_speed_ratio=tts_volc_speed_ratio,
        tts_volc_volume_ratio=tts_volc_volume_ratio,
        tts_volc_pitch_ratio=tts_volc_pitch_ratio,
        tts_volc_auth_style=tts_volc_auth_style,
        log_level=log_level,
        volc_app_id=volc_app_id,
        volc_access_token=volc_access_token,
        volc_secret_key=volc_secret_key,
        volc_asr_ws_url=volc_asr_ws_url,
        volc_tts_ws_url=volc_tts_ws_url,
        volc_asr_cluster=volc_asr_cluster,
        asr_provider=asr_provider,
        asr_base_url=asr_base_url,
        asr_api_key=asr_api_key,
        asr_app_id=asr_app_id,
        asr_access_token=asr_access_token,
        asr_secret_key=asr_secret_key,
        asr_auth_style=asr_auth_style,
        asr_model=asr_model,
        asr_language=asr_language,
        asr_max_audio_bytes=asr_max_audio_bytes,
        knowledge_http_port=knowledge_http_port,
        knowledge_ingest_token=knowledge_ingest_token,
        knowledge_data_path=knowledge_data_path,
        knowledge_context_max_chars=knowledge_context_max_chars,
        mirror_token=mirror_token,
        xiaozhi_mysql_host=xiaozhi_mysql_host,
        xiaozhi_mysql_port=xiaozhi_mysql_port,
        xiaozhi_mysql_user=xiaozhi_mysql_user,
        xiaozhi_mysql_password=xiaozhi_mysql_password,
        xiaozhi_mysql_db=xiaozhi_mysql_db,
        xiaozhi_agent_id=xiaozhi_agent_id,
        xiaozhi_prompt_refresh_seconds=xiaozhi_prompt_refresh_seconds,
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
    if settings.asr_provider not in {"openai", "volc"}:
        issues.append("ASR_PROVIDER must be 'openai' or 'volc'.")
    if settings.tts_provider not in {"edge", "volc"}:
        issues.append("TTS_PROVIDER must be 'edge' or 'volc'.")
    if settings.asr_provider == "volc":
        if not settings.asr_base_url:
            issues.append("ASR_BASE_URL is required when ASR_PROVIDER=volc.")
        if not (settings.asr_access_token or settings.volc_access_token):
            issues.append("ASR_ACCESS_TOKEN or VOLC_ACCESS_TOKEN is required when ASR_PROVIDER=volc.")
        if not (settings.asr_app_id or settings.volc_app_id):
            issues.append("ASR_APP_ID or VOLC_APP_ID is required when ASR_PROVIDER=volc.")
    if settings.tts_provider == "volc":
        if not (settings.tts_volc_base_url or settings.volc_tts_ws_url):
            issues.append("TTS_VOLC_BASE_URL or VOLC_TTS_WS_URL is required when TTS_PROVIDER=volc.")
        if not settings.volc_access_token:
            issues.append("VOLC_ACCESS_TOKEN is required when TTS_PROVIDER=volc.")
        if not settings.volc_app_id:
            issues.append("VOLC_APP_ID is required when TTS_PROVIDER=volc.")
    if settings.tts_volc_speed_ratio <= 0:
        issues.append("TTS_VOLC_SPEED_RATIO must be greater than 0.")
    if settings.tts_volc_volume_ratio <= 0:
        issues.append("TTS_VOLC_VOLUME_RATIO must be greater than 0.")
    if settings.tts_volc_pitch_ratio <= 0:
        issues.append("TTS_VOLC_PITCH_RATIO must be greater than 0.")
    if settings.tts_volc_auth_style not in {"bearer", "bearer_semicolon"}:
        issues.append("TTS_VOLC_AUTH_STYLE must be 'bearer', 'token', or 'auto'.")
    if settings.knowledge_http_port < 0 or settings.knowledge_http_port > 65535:
        issues.append("KNOWLEDGE_HTTP_PORT must be in range 0-65535 (0 = disable HTTP ingest).")
    if settings.knowledge_http_port > 0 and not settings.knowledge_ingest_token:
        issues.append("KNOWLEDGE_INGEST_TOKEN is required when KNOWLEDGE_HTTP_PORT > 0.")
    if settings.knowledge_context_max_chars < 0:
        issues.append("KNOWLEDGE_CONTEXT_MAX_CHARS must be non-negative.")
    return issues
