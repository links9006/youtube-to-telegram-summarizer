# all-youtube

> A self-hosted pipeline that turns YouTube videos into short, readable summaries delivered to a Telegram channel. Plug in a playlist, a search query, or send a link to a bot — get a clean Russian-language digest.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/links9006/all-youtube/ci.yml?branch=main)](.github/workflows/ci.yml)

## ✨ Features

- **Multiple ingest sources** — YouTube playlists (per-language), daily keyword search, one-off backlog import, and on-demand requests from a Telegram bot.
- **Audio extraction via Telegram** — uses a Telethon user session and an audio-extractor bot to download the audio track (works where `yt-dlp` audio is restricted).
- **Speech-to-text** — Russian videos are transcribed with [GigaAM](https://github.com/salute-developers/GigaAM); English videos with [OpenAI Whisper](https://github.com/openai/whisper).
- **LLM summarization** — summaries generated through [OpenRouter](https://openrouter.ai) with automatic multi-model fallback.
- **Channel publishing** — final summaries are posted to a Telegram channel; an optional digest worker compiles them into a second channel.
- **Resilient by design** — a single sequential ASR worker avoids GPU/CPU thrash; Telethon clients auto-reconnect on drops; every network call is bounded by a timeout.
- **SQLite-backed queue** — durable job state with deduplication by video and by destination.

## 🏗️ Architecture

```
                ┌────────────────────┐
 playlist/search │  producers         │
 bot requests ──▶│  (enqueue videos)  │
 backlog import  └─────────┬──────────┘
                           ▼
                  ┌────────────────┐     ┌───────────────┐
                  │   videos       │────▶│ worker_asr    │  download audio → mp3 → transcript
                  │  (SQLite queue)│     └───────┬───────┘
                  └────────────────┘             ▼ status=transcribed
                           ▲             ┌───────────────┐
                           │             │ worker_summary│  OpenRouter summary → publish to channel
                           │             └───────┬───────┘
                  ┌────────────────┐             ▼
                  │ worker_digest  │◀────────  published posts
                  └────────────────┘
```

### Modules ([`app/`](app/))

| Module | Role |
| --- | --- |
| [`app/bot_main.py`](app/bot_main.py) | aiogram Telegram bot (webhook). |
| [`app/worker_download_asr.py`](app/worker_download_asr.py) | The single sequential download + ASR worker. |
| [`app/worker_summary.py`](app/worker_summary.py) | Summarization + channel publishing. |
| [`app/worker_digest.py`](app/worker_digest.py) | Compiles posts into a digest channel. |
| [`app/producer_playlist.py`](app/producer_playlist.py) / [`producer_search_daily.py`](app/producer_search_daily.py) / [`producer_backlog.py`](app/producer_backlog.py) | Enqueue new videos. |
| [`app/telethon_downloader.py`](app/telethon_downloader.py) | Telethon client that fetches audio via an extractor bot. |
| [`app/asr.py`](app/asr.py) | GigaAM (RU) / Whisper (EN) transcription. |
| [`app/openrouter.py`](app/openrouter.py) | LLM summarization with multi-model fallback. |
| [`app/db.py`](app/db.py) | SQLite schema + queue helpers. |
| [`app/config.py`](app/config.py) | Environment-driven configuration. |

## 🚀 Quick Start

### Prerequisites

- Python **3.10+**
- `ffmpeg` and `ffprobe` on `PATH`
- A Telegram **user** account (for Telethon audio fetching) + a bot token (for the bot/publisher)
- A [YouTube Data API v3](https://developers.google.com/youtube/v3/getting-started) key
- An [OpenRouter](https://openrouter.ai) API key

### Install

```bash
git clone https://github.com/links9006/all-youtube.git
cd all-youtube

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your own keys, channels, and paths
```

### Configure

All configuration is read from environment variables (see [`app/config.py`](app/config.py)). Copy [`.env.example`](.env.example) to `.env` and fill in:

- `BOT_TOKEN` — Telegram bot token (from [@BotFather](https://t.me/BotFather)).
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — from <https://my.telegram.org>.
- `TELEGRAM_PHONE` — phone number of the user account used for audio fetching.
- `YOUTUBE_API_KEY` — YouTube Data API v3 key.
- `OPENROUTER_API_KEY` — OpenRouter key. `OPENROUTER_MODELS` is a comma-separated list (tried in random order with fallback).
- `TARGET_CHANNEL` — the channel where summaries are published (your bot must be admin).
- `PLAYLIST_RU_URL` / `PLAYLIST_EN_URL` / `SEARCH_QUERIES` — ingestion sources.

> ⚠️ **Never commit `.env` or `*.session` files.** They contain credentials. `.gitignore` already excludes them.

### Create the Telegram sessions

On first run, Telethon needs to authorize the user account (creates `telegram_session.session`):

```bash
python -c "import asyncio; from telethon import TelegramClient; from app import config; \
c=TelegramClient(config.TELEGRAM_SESSION, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH); \
import asyncio; asyncio.get_event_loop().run_until_complete(c.start(phone=config.TELEGRAM_PHONE))"
```

### Run

The intended deployment is via **systemd** (unit files live in [`systemd/`](systemd/)):

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now all-youtube-bot \
                       all-youtube-asr \
                       all-youtube-summary \
                       all-youtube-digest \
                       all-youtube-playlist-ru.timer \
                       all-youtube-playlist-en.timer \
                       all-youtube-search-daily.timer
```

For local testing you can run a single worker directly:

```bash
python -m app.worker_download_asr
python -m app.worker_summary
```

## 🛠️ Development

```bash
pip install -r requirements-dev.txt
ruff check app/          # lint
ruff format app/         # format
```

Pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). CI runs on every push via [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## 🔒 Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) — please report privately, not via a public issue.

## 📄 License

[MIT](LICENSE) © all-youtube contributors.

## 💛 Acknowledgements

- [Telethon](https://github.com/LonamiWebs/Telethon), [aiogram](https://aiogram.dev)
- [OpenAI Whisper](https://github.com/openai/whisper), [GigaAM](https://github.com/salute-developers/GigaAM)
- [OpenRouter](https://openrouter.ai)
