from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from telethon import TelegramClient

from app import config
from app.utils import has_cyrillic, log


# How many times we retry a single download after reconnecting the Telethon client.
DOWNLOAD_MAX_ATTEMPTS = 3
# Backoff (seconds) between reconnect attempts.
RECONNECT_BACKOFF_SECONDS = 5


def _find_audio_button(reply) -> tuple[int, int] | None:
    if not reply.buttons:
        return None
    for row_idx, row in enumerate(reply.buttons):
        for col_idx, button in enumerate(row):
            text = (getattr(button, "text", "") or "").lower()
            if "audio" in text:
                return row_idx, col_idx
    return None


def _is_audio_message(message) -> bool:
    if getattr(message, "audio", None) or getattr(message, "voice", None):
        return True
    document = getattr(message, "document", None)
    if not document:
        return False
    mime = (getattr(document, "mime_type", "") or "").lower()
    return mime.startswith("audio/")


def _message_text(message) -> str:
    parts: list[str] = []
    audio = getattr(message, "audio", None)
    if audio is not None:
        for value in (getattr(audio, "title", None), getattr(audio, "performer", None)):
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    document = getattr(message, "document", None)
    if document:
        for attr in getattr(document, "attributes", []) or []:
            for value in (getattr(attr, "file_name", None), getattr(attr, "title", None), getattr(attr, "performer", None)):
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    return " | ".join(parts)


def _is_disconnected_error(exc: Exception) -> bool:
    """True when an exception indicates the Telethon client lost its connection."""
    text = str(exc).lower()
    if "disconnected" in text or "connection" in text:
        return True
    # asyncio.TimeoutError is raised by our wait_for() wrappers when an RPC hangs,
    # which typically means the transport is dead.
    return isinstance(exc, (ConnectionError, asyncio.TimeoutError))


class TopsaversClient:
    def __init__(self) -> None:
        self.client = TelegramClient(config.TELEGRAM_SESSION, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)

    # --- low-level RPC wrapper: every Telethon call is bounded by a timeout ---
    async def _rpc(self, coro):
        """Await a Telethon call with a hard per-call timeout.

        Without this, a single get_messages()/send_message() on a dead transport
        blocks forever and wedges the whole worker (the polling-loop deadlines
        never get a chance to fire).
        """
        return await asyncio.wait_for(coro, timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS)

    async def connect(self) -> None:
        await self._rpc(self.client.connect())
        if not await self._rpc(self.client.is_user_authorized()):
            await self._rpc(self.client.start(phone=config.TELEGRAM_PHONE))

    async def disconnect(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:
            pass

    async def ensure_connected(self) -> None:
        """Reconnect the client if it dropped.

        Telethon does not reliably auto-reconnect after repeated failures, so a
        single network blip leaves the client permanently disconnected and every
        subsequent request raises 'Cannot send requests while disconnected'.
        We guard each operation by checking the connection state here.
        """
        try:
            connected = await asyncio.wait_for(
                self.client.is_connected(), timeout=config.TELEGRAM_RPC_TIMEOUT_SECONDS
            )
            if connected:
                return
        except Exception:
            pass
        log("Telegram client disconnected, reconnecting...")
        # Disconnect fully first to clear any half-open socket state.
        try:
            await self.client.disconnect()
        except Exception:
            pass
        attempt = 0
        while True:
            attempt += 1
            try:
                await self.client.connect()
                if await self.client.is_user_authorized():
                    log(f"Telegram client reconnected (attempt {attempt})")
                    return
                # Transport is up but session not authorized -> try start.
                await self.client.start(phone=config.TELEGRAM_PHONE)
                log(f"Telegram client restarted (attempt {attempt})")
                return
            except Exception as exc:
                log(f"Reconnect attempt {attempt} failed: {exc}")
                if attempt >= 5:
                    raise
                await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)

    async def _wait_for_reply(self, entity, after_id: int):
        deadline = asyncio.get_event_loop().time() + config.BOT_REPLY_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            messages = await self._rpc(self.client.get_messages(entity, limit=20))
            for message in reversed([m for m in messages if m and m.id > after_id and not getattr(m, "out", False)]):
                return message
            await asyncio.sleep(1)
        raise TimeoutError("topsaversbot did not answer")

    async def _wait_for_button(self, entity, after_id: int):
        deadline = asyncio.get_event_loop().time() + config.AUDIO_BUTTON_WAIT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            messages = await self._rpc(self.client.get_messages(entity, limit=20))
            for message in reversed([m for m in messages if m and m.id >= after_id]):
                position = _find_audio_button(message)
                if position is not None:
                    return message, position
            await asyncio.sleep(1)
        raise TimeoutError("audio button not found")

    async def _wait_for_audio(self, entity, after_id: int):
        deadline = asyncio.get_event_loop().time() + config.AUDIO_MEDIA_WAIT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            messages = await self._rpc(self.client.get_messages(entity, limit=30))
            for message in reversed([m for m in messages if m and m.id >= after_id]):
                if _is_audio_message(message):
                    return message
            await asyncio.sleep(config.AUDIO_POLL_INTERVAL_SECONDS)
        raise TimeoutError("audio was not received")

    async def _download_audio_once(self, youtube_url: str, output_dir: Path) -> tuple[Path, str]:
        entity = await self._rpc(self.client.get_entity(config.TOPSAVERS_BOT_USERNAME))
        sent = await self._rpc(self.client.send_message(entity, youtube_url))
        reply = await self._wait_for_reply(entity, sent.id)
        button_msg, position = await self._wait_for_button(entity, reply.id)
        await self._rpc(button_msg.click(*position))
        audio_message = await self._wait_for_audio(entity, button_msg.id)

        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = await self._rpc(
            self.client.download_media(audio_message, file=str(output_dir / "source_audio"))
        )
        source_path = Path(downloaded)
        mp3_path = output_dir / "audio.mp3"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(mp3_path)],
            capture_output=True,
            text=True,
        )
        source_path.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffmpeg convert failed")
        language = "ru" if has_cyrillic(_message_text(audio_message)) else "en"
        return mp3_path, language

    async def download_audio(self, youtube_url: str, output_dir: Path) -> tuple[Path, str]:
        """Download the audio track, auto-reconnecting the client on connection drops."""
        last_exc: Exception | None = None
        for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                await self.ensure_connected()
                return await self._download_audio_once(youtube_url, output_dir)
            except Exception as exc:
                last_exc = exc
                if _is_disconnected_error(exc) and attempt < DOWNLOAD_MAX_ATTEMPTS:
                    log(f"download_audio attempt {attempt} hit a connection/timeout error ({exc}); reconnecting and retrying")
                    try:
                        await self.ensure_connected()
                    except Exception as rec_exc:
                        log(f"reconnect after failure raised: {rec_exc}")
                    await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)
                    continue
                # Non-connection error (e.g. 'audio was not received') or out of attempts.
                raise
        raise last_exc  # type: ignore[misc]
