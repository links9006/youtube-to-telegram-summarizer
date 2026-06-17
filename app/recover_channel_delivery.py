from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from dataclasses import dataclass

from aiogram import Bot
from telethon.errors import FloodWaitError
from telethon import TelegramClient
from telethon.sessions import StringSession

from app import config
from app.db import Database
from app.utils import log, split_for_telegram


LOGGER = logging.getLogger(__name__)
TELEGRAM_SEND_DELAY_SECONDS = 2.0
FLOOD_WAIT_BUFFER_SECONDS = 5


@dataclass(slots=True)
class RecoveryStats:
    delivered_ready: int = 0
    requeued_summary: int = 0
    requeued_asr: int = 0


async def _send_text(bot: Bot, destination: str | int, text: str) -> None:
    for chunk in split_for_telegram(text, 3500):
        await bot.send_message(chat_id=destination, text=chunk)
        await asyncio.sleep(TELEGRAM_SEND_DELAY_SECONDS)


async def _send_via_telethon(client: TelegramClient, destination: str, text: str) -> None:
    entity = await client.get_entity(destination)
    for chunk in split_for_telegram(text, 3500):
        await client.send_message(entity, chunk)
        await asyncio.sleep(TELEGRAM_SEND_DELAY_SECONDS)


async def _connect_publisher_client() -> TelegramClient:
    tg_session = StringSession(config.TELEGRAM_PUBLISHER_STRING_SESSION) if config.TELEGRAM_PUBLISHER_STRING_SESSION else config.TELEGRAM_PUBLISHER_SESSION
    client = TelegramClient(tg_session, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.start(phone=config.TELEGRAM_PHONE)
    return client


async def _reconnect_publisher_client(client: TelegramClient | None) -> TelegramClient:
    if client is not None:
        with contextlib.suppress(Exception):
            await client.disconnect()
    return await _connect_publisher_client()


async def _deliver_request(bot: Bot, tg_client: TelegramClient, request, summary: str) -> TelegramClient:
    if request["destination_type"] == "telegram_user":
        await _send_text(bot, int(request["telegram_user_id"]), summary)
        return tg_client

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            await _send_via_telethon(tg_client, request["telegram_chat_id"], summary)
            return tg_client
        except FloodWaitError as exc:
            last_error = exc
            wait_seconds = int(exc.seconds) + FLOOD_WAIT_BUFFER_SECONDS
            LOGGER.warning(
                "Telethon FloodWait for %s on attempt %s/3, sleeping %s seconds",
                request["telegram_chat_id"],
                attempt,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
            tg_client = await _reconnect_publisher_client(tg_client)
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


async def _deliver_pending_ready(db: Database, bot: Bot, tg_client: TelegramClient, limit: int | None) -> int:
    query = """
        SELECT DISTINCT v.id, v.summary_text
        FROM videos v
        JOIN requests r ON r.video_id = v.id
        WHERE r.delivered_at IS NULL
          AND v.summary_text IS NOT NULL
          AND TRIM(v.summary_text) <> ''
        ORDER BY v.id ASC
    """
    delivered = 0
    with db.connect() as conn:
        rows = conn.execute(query).fetchall()
    for row in rows:
        if limit is not None and delivered >= limit:
            break
        video_id = int(row["id"])
        summary = str(row["summary_text"])
        pending = db.pending_delivery_rows(video_id)
        if not pending:
            continue
        for request in pending:
            tg_client = await _deliver_request(bot, tg_client, request, summary)
            db.mark_request_delivered(int(request["id"]))
        delivered += 1
        log(f"recovery delivered ready summary video_id={video_id}")
    return delivered


def _requeue_summary_stage(db: Database, limit: int | None) -> int:
    query = """
        SELECT DISTINCT v.id
        FROM videos v
        JOIN requests r ON r.video_id = v.id
        WHERE r.delivered_at IS NULL
          AND (
                v.status = 'summarizing'
                OR (v.status = 'failed' AND v.transcript_text IS NOT NULL AND TRIM(v.transcript_text) <> '')
              )
          AND (v.summary_text IS NULL OR TRIM(v.summary_text) = '')
        ORDER BY v.id ASC
    """
    with db.connect() as conn:
        rows = conn.execute(query).fetchall()
        target_ids = [int(row["id"]) for row in rows[:limit] if row is not None] if limit is not None else [int(row["id"]) for row in rows]
        for video_id in target_ids:
            conn.execute(
                """
                UPDATE videos
                SET status = 'transcribed', error_text = NULL, summary_started_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (video_id,),
            )
    for video_id in target_ids:
        log(f"recovery requeued summary video_id={video_id}")
    return len(target_ids)


def _requeue_asr_stage(db: Database, limit: int | None) -> int:
    query = """
        SELECT DISTINCT v.id
        FROM videos v
        JOIN requests r ON r.video_id = v.id
        WHERE r.delivered_at IS NULL
          AND (
                v.status IN ('processing_asr', 'queued')
                OR (v.status = 'failed' AND (v.transcript_text IS NULL OR TRIM(v.transcript_text) = ''))
              )
        ORDER BY v.id ASC
    """
    with db.connect() as conn:
        rows = conn.execute(query).fetchall()
        target_ids = [int(row["id"]) for row in rows[:limit] if row is not None] if limit is not None else [int(row["id"]) for row in rows]
        for video_id in target_ids:
            conn.execute(
                """
                UPDATE videos
                SET status = 'queued', error_text = NULL, asr_started_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (video_id,),
            )
    for video_id in target_ids:
        log(f"recovery requeued asr video_id={video_id}")
    return len(target_ids)


async def _async_main(mode: str, limit: int | None) -> int:
    config.ensure_dirs()
    config.validate_worker_config()
    db = Database()
    db.init()
    stats = RecoveryStats()

    if mode in {"deliver-ready", "all"}:
        bot = Bot(token=config.BOT_TOKEN)
        tg_client = await _connect_publisher_client()
        try:
            stats.delivered_ready = await _deliver_pending_ready(db, bot, tg_client, limit)
        finally:
            with contextlib.suppress(Exception):
                await tg_client.disconnect()
            with contextlib.suppress(Exception):
                await bot.session.close()

    if mode in {"requeue-summary", "all"}:
        stats.requeued_summary = _requeue_summary_stage(db, limit)

    if mode in {"requeue-asr", "all"}:
        stats.requeued_asr = _requeue_asr_stage(db, limit)

    log(
        "recovery complete "
        f"delivered_ready={stats.delivered_ready} "
        f"requeued_summary={stats.requeued_summary} "
        f"requeued_asr={stats.requeued_asr}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["deliver-ready", "requeue-summary", "requeue-asr", "all"],
        default="all",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    limit = args.limit if args.limit > 0 else None
    return asyncio.run(_async_main(args.mode, limit))


if __name__ == "__main__":
    raise SystemExit(main())