from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from app import config


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_video_id TEXT NOT NULL UNIQUE,
    youtube_url TEXT NOT NULL,
    title TEXT,
    language TEXT,
    transcript_text TEXT,
    summary_text TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing_asr','transcribed','summarizing','done','failed')),
    error_text TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    asr_started_at DATETIME,
    summary_started_at DATETIME,
    completed_at DATETIME
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    priority INTEGER NOT NULL,
    destination_type TEXT NOT NULL CHECK(destination_type IN ('telegram_user','telegram_chat')),
    destination_key TEXT NOT NULL,
    telegram_user_id INTEGER,
    telegram_chat_id TEXT,
    telegram_message_thread_id INTEGER,
    meta_json TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at DATETIME,
    failed_at DATETIME,
    UNIQUE(video_id, destination_key)
);

CREATE INDEX IF NOT EXISTS idx_requests_pending_order
ON requests(delivered_at, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_videos_status
ON videos(status, created_at);

CREATE TABLE IF NOT EXISTS digest_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chat_id TEXT NOT NULL,
    source_message_id INTEGER NOT NULL,
    source_video_id TEXT,
    source_post_url TEXT NOT NULL,
    source_started_at DATETIME,
    source_finished_at DATETIME NOT NULL,
    source_text TEXT NOT NULL,
    generated_title TEXT,
    generated_description TEXT,
    target_chat_id TEXT,
    target_message_id INTEGER,
    published_at DATETIME,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','published','failed')),
    error_text TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_chat_id, source_message_id)
);

CREATE TABLE IF NOT EXISTS digest_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_digest_posts_status
ON digest_posts(status, created_at);
"""


@dataclass(slots=True)
class VideoJob:
    id: int
    youtube_video_id: str
    youtube_url: str
    title: str | None
    language: str | None
    transcript_text: str | None
    summary_text: str | None
    status: str


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.DB_PATH

    def init(self) -> None:
        config.ensure_dirs()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def enqueue_video_request(
        self,
        *,
        youtube_url: str,
        youtube_video_id: str,
        title: str | None,
        language: str | None,
        priority: int,
        source_type: str,
        destination_type: str,
        destination_key: str,
        telegram_user_id: int | None = None,
        telegram_chat_id: str | None = None,
        telegram_message_thread_id: int | None = None,
        meta_json: str | None = None,
    ) -> tuple[int, bool, bool]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM videos WHERE youtube_video_id = ?",
                (youtube_video_id,),
            ).fetchone()
            created_video = False
            if row:
                video_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE videos
                    SET youtube_url = ?,
                        title = COALESCE(title, ?),
                        language = COALESCE(language, ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (youtube_url, title, language, video_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO videos(youtube_video_id, youtube_url, title, language, status)
                    VALUES(?, ?, ?, ?, 'queued')
                    """,
                    (youtube_video_id, youtube_url, title, language),
                )
                video_id = int(cur.lastrowid)
                created_video = True

            inserted_request = False
            existing_request = conn.execute(
                "SELECT id FROM requests WHERE video_id = ? AND destination_key = ?",
                (video_id, destination_key),
            ).fetchone()
            if not existing_request:
                conn.execute(
                    """
                    INSERT INTO requests(
                        video_id, source_type, priority, destination_type, destination_key,
                        telegram_user_id, telegram_chat_id, telegram_message_thread_id, meta_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        source_type,
                        priority,
                        destination_type,
                        destination_key,
                        telegram_user_id,
                        telegram_chat_id,
                        telegram_message_thread_id,
                        meta_json,
                    ),
                )
                inserted_request = True
            return video_id, created_video, inserted_request

    def _claim_video(self, target_status: str, next_status: str, started_column: str) -> VideoJob | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"""
                SELECT v.*
                FROM videos v
                JOIN requests r ON r.video_id = v.id
                WHERE v.status = ?
                  AND r.delivered_at IS NULL
                GROUP BY v.id
                ORDER BY MIN(r.priority) ASC, MIN(r.created_at) ASC, v.id ASC
                LIMIT 1
                """,
                (target_status,),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                f"UPDATE videos SET status = ?, {started_column} = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (next_status, int(row["id"])),
            )
            conn.execute("COMMIT")
            claimed = conn.execute("SELECT * FROM videos WHERE id = ?", (int(row["id"]),)).fetchone()
            if not claimed:
                return None
            return VideoJob(
                id=int(claimed["id"]),
                youtube_video_id=str(claimed["youtube_video_id"]),
                youtube_url=str(claimed["youtube_url"]),
                title=claimed["title"],
                language=claimed["language"],
                transcript_text=claimed["transcript_text"],
                summary_text=claimed["summary_text"],
                status=str(claimed["status"]),
            )

    def claim_next_for_asr(self) -> VideoJob | None:
        return self._claim_video("queued", "processing_asr", "asr_started_at")

    def claim_next_for_summary(self) -> VideoJob | None:
        return self._claim_video("transcribed", "summarizing", "summary_started_at")

    def update_video_language(self, video_id: int, language: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE videos SET language = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (language, video_id),
            )

    def set_transcript(self, video_id: int, transcript_text: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE videos
                SET transcript_text = ?, status = 'transcribed', error_text = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (transcript_text, video_id),
            )

    def set_summary(self, video_id: int, summary_text: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE videos
                SET summary_text = ?, status = 'done', error_text = NULL,
                    completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (summary_text, video_id),
            )

    def fail_video(self, video_id: int, error_text: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE videos SET status = 'failed', error_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (error_text[:4000], video_id),
            )

    def pending_delivery_rows(self, video_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM requests WHERE video_id = ? AND delivered_at IS NULL ORDER BY priority, created_at, id",
                (video_id,),
            ).fetchall()

    def mark_request_delivered(self, request_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE requests SET delivered_at = CURRENT_TIMESTAMP WHERE id = ?", (request_id,))