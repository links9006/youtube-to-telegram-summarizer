from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot
from telethon import TelegramClient
from telethon.sessions import StringSession

from app import config
from app.db import Database
from app.openrouter import summarize_video
from app.utils import log, split_for_telegram


LOGGER = logging.getLogger(__name__)

# Max reconnect attempts when (re)establishing the publisher Telethon session.
PUBLISHER_CONNECT_ATTEMPTS = 5
PUBLISHER_BACKOFF_SECONDS = 5


async def _send_text(bot: Bot, destination: str | int, text: str) -> None:
    for chunk in split_for_telegram(text, 3500):
        await asyncio.wait_for(
            bot.send_message(chat_id=destination, text=chunk),
            timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS,
        )


async def _send_via_telethon(client: TelegramClient, destination: str, text: str) -> None:
    entity = await asyncio.wait_for(
        client.get_entity(destination), timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS
    )
    for chunk in split_for_telegram(text, 3500):
        await asyncio.wait_for(
            client.send_message(entity, chunk), timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS
        )


async def _connect_publisher_client() -> TelegramClient:
    tg_session = (
        StringSession(config.TELEGRAM_PUBLISHER_STRING_SESSION)
        if config.TELEGRAM_PUBLISHER_STRING_SESSION
        else config.TELEGRAM_PUBLISHER_SESSION
    )
    client = TelegramClient(tg_session, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
    # Bound every connect/authorize step so a dead transport can't hang the worker.
    await asyncio.wait_for(client.connect(), timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS)
    authorized = await asyncio.wait_for(
        client.is_user_authorized(), timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS
    )
    if not authorized:
        await asyncio.wait_for(
            client.start(phone=config.TELEGRAM_PHONE),
            timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS * 2,
        )
    return client


async def _reconnect_publisher_client(client: TelegramClient | None) -> TelegramClient:
    """Best-effort reconnect of the publisher Telethon client with retries."""
    if client is not None:
        with contextlib.suppress(Exception):
            await client.disconnect()
    last_exc: Exception | None = None
    for attempt in range(1, PUBLISHER_CONNECT_ATTEMPTS + 1):
        try:
            return await _connect_publisher_client()
        except Exception as exc:
            last_exc = exc
            LOGGER.warning("publisher reconnect attempt %s/%s failed: %s", attempt, PUBLISHER_CONNECT_ATTEMPTS, exc)
            if attempt < PUBLISHER_CONNECT_ATTEMPTS:
                await asyncio.sleep(PUBLISHER_BACKOFF_SECONDS)
    raise RuntimeError(f"publisher reconnect failed after {PUBLISHER_CONNECT_ATTEMPTS} attempts: {last_exc}")


async def _deliver_request(bot: Bot, tg_client: TelegramClient, request, summary: str) -> None:
    if request["destination_type"] == "telegram_user":
        await _send_text(bot, int(request["telegram_user_id"]), summary)
        return

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            await _send_via_telethon(tg_client, request["telegram_chat_id"], summary)
            return
        except Exception as exc:
            last_error = exc
            LOGGER.warning(
                "Telethon delivery failed for %s on attempt %s/3: %s",
                request["telegram_chat_id"],
                attempt,
                exc,
            )
            if attempt < 3:
                await asyncio.sleep(min(attempt * 2, 5))
                tg_client = await _reconnect_publisher_client(tg_client)

    raise RuntimeError(f"Telethon delivery failed after retries: {last_error}")


async def main() -> None:
    config.ensure_dirs()
    config.validate_worker_config()
    db = Database()
    db.init()
    bot = Bot(token=config.BOT_TOKEN)
    tg_client = await _connect_publisher_client()
    try:
        while True:
            job = db.claim_next_for_summary()
            if not job:
                await asyncio.sleep(5)
                continue
            try:
                summary = summarize_video(job.title or job.youtube_video_id, job.youtube_url, job.transcript_text or "")
                db.set_summary(job.id, summary)
                for request in db.pending_delivery_rows(job.id):
                    await _deliver_request(bot, tg_client, request, summary)
                    db.mark_request_delivered(int(request["id"]))
                log(f"Summary delivered {job.youtube_video_id}")
            except Exception as exc:
                db.fail_video(job.id, str(exc))
                log(f"Summary failed {job.youtube_video_id}: {exc}")
                if any(token in str(exc).lower() for token in ("telethon", "connection", "security error", "reset by peer", "disconnected", "timeout")):
                    with contextlib.suppress(Exception):
                        tg_client = await _reconnect_publisher_client(tg_client)
    finally:
        with contextlib.suppress(Exception):
            await tg_client.disconnect()
        with contextlib.suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
