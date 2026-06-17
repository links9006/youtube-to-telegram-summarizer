from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


BOT_TOKEN = _get("BOT_TOKEN")
WEBHOOK_BASE_URL = _get("WEBHOOK_BASE_URL")
WEBHOOK_PATH = _get("WEBHOOK_PATH", "/yt/") or "/yt/"
WEBHOOK_HOST = _get("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = _get_int("WEBHOOK_PORT", 8081)
USE_WEBHOOK = _get_bool("USE_WEBHOOK", True)

STEP1_SERVICE_HOST = _get("STEP1_SERVICE_HOST", "127.0.0.1")
STEP1_SERVICE_PORT = _get_int("STEP1_SERVICE_PORT", 8091)

TELEGRAM_API_ID = _get_int("TELEGRAM_API_ID", 0)
TELEGRAM_API_HASH = _get("TELEGRAM_API_HASH")
TELEGRAM_PHONE = _get("TELEGRAM_PHONE")
TELEGRAM_SESSION = _get("TELEGRAM_SESSION", str(BASE_DIR / "telegram_session"))
TELEGRAM_PUBLISHER_SESSION = _get("TELEGRAM_PUBLISHER_SESSION", str(BASE_DIR / "telegram_publisher_session"))
TELEGRAM_PUBLISHER_STRING_SESSION = _get("TELEGRAM_PUBLISHER_STRING_SESSION")
TOPSAVERS_BOT_USERNAME = _get("TOPSAVERS_BOT_USERNAME", "topsaversbot")
TELEGRAM_RPC_TIMEOUT_SECONDS = _get_int("TELEGRAM_RPC_TIMEOUT_SECONDS", 60)
BOT_REPLY_TIMEOUT_SECONDS = _get_int("BOT_REPLY_TIMEOUT_SECONDS", 30)
AUDIO_MEDIA_WAIT_SECONDS = _get_int("AUDIO_MEDIA_WAIT_SECONDS", 180)
AUDIO_BUTTON_WAIT_SECONDS = _get_int("AUDIO_BUTTON_WAIT_SECONDS", 30)
AUDIO_POLL_INTERVAL_SECONDS = _get_int("AUDIO_POLL_INTERVAL_SECONDS", 3)

HUGGINGFACE_API_KEY = _get("HUGGINGFACE_API_KEY")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
OPENROUTER_URL = _get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS = [
    item.strip()
    for item in _get(
        "OPENROUTER_MODELS",
        "openrouter/owl-alpha,nvidia/nemotron-3-ultra-550b-a55b:free,nex-agi/nex-n2-pro:free,poolside/laguna-m.1:free,nvidia/nemotron-3-super-120b-a12b:free",
    ).split(",")
    if item.strip()
]
YOUTUBE_API_KEY = _get("YOUTUBE_API_KEY")

DB_PATH = Path(_get("DB_PATH", str(BASE_DIR / "data" / "all_youtube.sqlite3")))
DOWNLOAD_DIR = Path(_get("DOWNLOAD_DIR", str(BASE_DIR / "data" / "downloads")))
TRANSCRIPTS_DIR = Path(_get("TRANSCRIPTS_DIR", str(BASE_DIR / "data" / "transcripts")))
LOG_DIR = Path(_get("LOG_DIR", str(BASE_DIR / "logs")))
STEP1_CACHE_DIR = Path(_get("STEP1_CACHE_DIR", str(DOWNLOAD_DIR / "step1_service")))

TARGET_CHANNEL = _get("TARGET_CHANNEL", "@your_main_channel")
DIGEST_SOURCE_CHANNEL = _get("DIGEST_SOURCE_CHANNEL", TARGET_CHANNEL or "@your_main_channel")
DIGEST_TARGET_CHANNEL = _get("DIGEST_TARGET_CHANNEL", "@your_digest_channel")
DIGEST_POLL_SECONDS = _get_int("DIGEST_POLL_SECONDS", 300)
DIGEST_TELEGRAM_SEND_DELAY_SECONDS = _get_int("DIGEST_TELEGRAM_SEND_DELAY_SECONDS", 3)
DIGEST_BOOTSTRAP_LIMIT = _get_int("DIGEST_BOOTSTRAP_LIMIT", 10)

PLAYLIST_RU_URL = _get("PLAYLIST_RU_URL", "https://youtube.com/playlist?list=YOUR_RU_PLAYLIST_ID")
PLAYLIST_EN_URL = _get("PLAYLIST_EN_URL", "https://youtube.com/playlist?list=YOUR_EN_PLAYLIST_ID")
SEARCH_QUERIES = [item.strip() for item in _get("SEARCH_QUERIES", "ai tools,ai service,ai news").split(",") if item.strip()]
SEARCH_MAX_RESULTS = _get_int("SEARCH_MAX_RESULTS", 4)

BACKLOG_FILES = [
    item.strip()
    for item in _get(
        "BACKLOG_FILES",
        "/home/ubuntu/youtube-to-tg/download.txt,/home/ubuntu/youtube-to-tg/download2.txt,/home/ubuntu/youtube-to-tg/download3.txt",
    ).split(",")
    if item.strip()
]
BACKLOG_PROCESSED_DIR = Path(_get("BACKLOG_PROCESSED_DIR", "/home/ubuntu/youtube-to-tg/youtube/ted-out/"))

WHISPER_MODELS = [item.strip() for item in _get("WHISPER_MODELS", "turbo,small").split(",") if item.strip()]
GIGAAM_CHUNK_SECONDS = _get_int("GIGAAM_CHUNK_SECONDS", 30)
MAX_TRANSCRIPT_CHARS = _get_int("MAX_TRANSCRIPT_CHARS", 200000)


def ensure_dirs() -> None:
    for path in (DB_PATH.parent, DOWNLOAD_DIR, TRANSCRIPTS_DIR, LOG_DIR, STEP1_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def validate_bot_config() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    if USE_WEBHOOK and not WEBHOOK_BASE_URL:
        raise RuntimeError("WEBHOOK_BASE_URL is required in webhook mode")


def validate_worker_config() -> None:
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_API_ID": TELEGRAM_API_ID,
        "TELEGRAM_API_HASH": TELEGRAM_API_HASH,
        "TELEGRAM_PHONE": TELEGRAM_PHONE,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")


def validate_digest_config() -> None:
    required = {
        "TELEGRAM_API_ID": TELEGRAM_API_ID,
        "TELEGRAM_API_HASH": TELEGRAM_API_HASH,
        "TELEGRAM_PHONE": TELEGRAM_PHONE,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
        "DIGEST_SOURCE_CHANNEL": DIGEST_SOURCE_CHANNEL,
        "DIGEST_TARGET_CHANNEL": DIGEST_TARGET_CHANNEL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required digest configuration: {', '.join(missing)}")