from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from app import config
from app.db import Database
from app.openrouter import summarize_digest_post
from app.utils import extract_video_id, find_urls, log, split_for_telegram


STATE_LAST_PROCESSED_MESSAGE_ID = "digest_last_processed_message_id"
STATE_BOOTSTRAP_DONE = "digest_bootstrap_done"


@dataclass(slots=True)
class SourcePost:
    source_chat_id: str
    source_message_id: int
    source_post_url: str
    source_started_at: str | None
    source_finished_at: str
    source_text: str
    source_video_id: str | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tg_session() -> StringSession | str:
    return StringSession(config.TELEGRAM_PUBLISHER_STRING_SESSION) if config.TELEGRAM_PUBLISHER_STRING_SESSION else config.TELEGRAM_PUBLISHER_SESSION


async def _connect_client() -> TelegramClient:
    client = TelegramClient(_tg_session(), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.start(phone=config.TELEGRAM_PHONE)
    return client


def _state_get(db: Database, key: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT state_value FROM digest_state WHERE state_key = ?", (key,)).fetchone()
        return str(row["state_value"]) if row else None


def _state_set(db: Database, key: str, value: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO digest_state(state_key, state_value, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )


def _digest_post_exists(db: Database, source_chat_id: str, source_message_id: int) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM digest_posts WHERE source_chat_id = ? AND source_message_id = ?",
            (source_chat_id, source_message_id),
        ).fetchone()
        return row is not None


def _save_digest_post(db: Database, post: SourcePost, title: str, description: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO digest_posts(
                source_chat_id, source_message_id, source_video_id, source_post_url,
                source_started_at, source_finished_at, source_text,
                generated_title, generated_description, status, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(source_chat_id, source_message_id) DO UPDATE SET
                source_video_id = excluded.source_video_id,
                source_post_url = excluded.source_post_url,
                source_started_at = excluded.source_started_at,
                source_finished_at = excluded.source_finished_at,
                source_text = excluded.source_text,
                generated_title = excluded.generated_title,
                generated_description = excluded.generated_description,
                error_text = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                post.source_chat_id,
                post.source_message_id,
                post.source_video_id,
                post.source_post_url,
                post.source_started_at,
                post.source_finished_at,
                post.source_text,
                title,
                description,
            ),
        )


def _mark_digest_failed(db: Database, source_chat_id: str, source_message_id: int, error_text: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE digest_posts SET status = 'failed', error_text = ?, updated_at = CURRENT_TIMESTAMP WHERE source_chat_id = ? AND source_message_id = ?",
            (error_text[:4000], source_chat_id, source_message_id),
        )


def _mark_digest_published(
    db: Database,
    source_chat_id: str,
    source_message_id: int,
    target_chat_id: str,
    target_message_id: int,
) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE digest_posts
            SET status = 'published',
                target_chat_id = ?,
                target_message_id = ?,
                published_at = CURRENT_TIMESTAMP,
                error_text = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE source_chat_id = ? AND source_message_id = ?
            """,
            (target_chat_id, target_message_id, source_chat_id, source_message_id),
        )


def _build_post_url(channel_username: str, message_id: int) -> str:
    return f"https://t.me/{channel_username.lstrip('@')}/{message_id}"


def _message_video_id(message) -> str | None:
    text = message.message or ""
    for url in find_urls(text):
        video_id = extract_video_id(url)
        if video_id:
            return video_id
    media = getattr(message, "media", None)
    webpage = getattr(media, "webpage", None) if media else None
    for value in (getattr(webpage, "url", None), getattr(webpage, "display_url", None)):
        if value:
            video_id = extract_video_id(str(value))
            if video_id:
                return video_id
    return None


async def _iter_source_messages(client: TelegramClient, entity, *, min_id: int = 0) -> list:
    items = []
    async for message in client.iter_messages(entity, limit=None, min_id=min_id, reverse=True):
        items.append(message)
    return items


def _group_messages(messages: Iterable, channel_username: str) -> list[SourcePost]:
    grouped: list[SourcePost] = []
    buffer: list = []
    for message in messages:
        if not (message.message or "").strip() and not getattr(message, "media", None):
            continue
        buffer.append(message)
        video_id = _message_video_id(message)
        if not video_id:
            continue
        source_text = "\n\n".join((item.message or "").strip() for item in buffer if (item.message or "").strip()).strip()
        first = buffer[0]
        last = buffer[-1]
        grouped.append(
            SourcePost(
                source_chat_id=channel_username,
                source_message_id=int(last.id),
                source_post_url=_build_post_url(channel_username, int(last.id)),
                source_started_at=first.date.isoformat() if first.date else None,
                source_finished_at=last.date.isoformat() if last.date else _utc_now_iso(),
                source_text=source_text,
                source_video_id=video_id,
            )
        )
        buffer = []
    return grouped


def _format_digest_message(title: str, description: str, url: str) -> str:
    return f"{title}\n\n{description}\n\nЧитать полностью: {url}"


async def _send_with_delay(client: TelegramClient, destination: str, text: str) -> int:
    entity = await client.get_entity(destination)
    last_message_id = 0
    for chunk in split_for_telegram(text, 3500):
        sent = await client.send_message(entity, chunk)
        last_message_id = int(sent.id)
        await asyncio.sleep(config.DIGEST_TELEGRAM_SEND_DELAY_SECONDS)
    return last_message_id


async def _publish_digest(db: Database, client: TelegramClient, post: SourcePost) -> None:
    if _digest_post_exists(db, post.source_chat_id, post.source_message_id):
        return
    title, description = summarize_digest_post(post.source_text, post.source_post_url)
    _save_digest_post(db, post, title, description)
    try:
        target_message_id = await _send_with_delay(client, config.DIGEST_TARGET_CHANNEL, _format_digest_message(title, description, post.source_post_url))
    except FloodWaitError as exc:
        await asyncio.sleep(int(exc.seconds) + 5)
        target_message_id = await _send_with_delay(client, config.DIGEST_TARGET_CHANNEL, _format_digest_message(title, description, post.source_post_url))
    _mark_digest_published(db, post.source_chat_id, post.source_message_id, config.DIGEST_TARGET_CHANNEL, target_message_id)
    _state_set(db, STATE_LAST_PROCESSED_MESSAGE_ID, str(post.source_message_id))
    log(f"Digest published source_message_id={post.source_message_id} video_id={post.source_video_id}")


async def _bootstrap_posts(db: Database, client: TelegramClient, source_entity) -> int:
    messages = await _iter_source_messages(client, source_entity, min_id=0)
    posts = _group_messages(messages, config.DIGEST_SOURCE_CHANNEL)
    processed = 0
    for post in posts[: config.DIGEST_BOOTSTRAP_LIMIT]:
        try:
            await _publish_digest(db, client, post)
            processed += 1
        except Exception as exc:
            _mark_digest_failed(db, post.source_chat_id, post.source_message_id, str(exc))
            log(f"Digest bootstrap failed source_message_id={post.source_message_id}: {exc}")
    _state_set(db, STATE_BOOTSTRAP_DONE, "1")
    return processed


async def _process_new_posts(db: Database, client: TelegramClient, source_entity) -> int:
    last_processed_raw = _state_get(db, STATE_LAST_PROCESSED_MESSAGE_ID)
    last_processed = int(last_processed_raw) if last_processed_raw and last_processed_raw.isdigit() else 0
    messages = await _iter_source_messages(client, source_entity, min_id=last_processed)
    posts = [post for post in _group_messages(messages, config.DIGEST_SOURCE_CHANNEL) if post.source_message_id > last_processed]
    processed = 0
    for post in posts:
        try:
            await _publish_digest(db, client, post)
            processed += 1
        except Exception as exc:
            _mark_digest_failed(db, post.source_chat_id, post.source_message_id, str(exc))
            log(f"Digest publish failed source_message_id={post.source_message_id}: {exc}")
    return processed


async def main() -> None:
    config.ensure_dirs()
    config.validate_digest_config()
    db = Database()
    db.init()
    client = await _connect_client()
    try:
        source_entity = await client.get_entity(config.DIGEST_SOURCE_CHANNEL)
        bootstrap_done = _state_get(db, STATE_BOOTSTRAP_DONE) == "1"
        if not bootstrap_done:
            processed = await _bootstrap_posts(db, client, source_entity)
            log(f"Digest bootstrap complete processed={processed}")
        while True:
            processed = await _process_new_posts(db, client, source_entity)
            if processed:
                log(f"Digest poll processed={processed}")
            await asyncio.sleep(config.DIGEST_POLL_SECONDS)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())