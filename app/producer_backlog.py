from __future__ import annotations

from pathlib import Path

from app import config
from app.db import Database
from app.utils import extract_video_id, log, read_nonempty_lines


def _processed_video_ids_from_dir(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    for item in path.rglob("*.txt"):
        parts = item.stem.split("_")
        if parts:
            result.add(parts[-1])
    return result


def main() -> int:
    db = Database()
    db.init()
    processed = _processed_video_ids_from_dir(config.BACKLOG_PROCESSED_DIR)
    added = 0
    for file_path in config.BACKLOG_FILES:
        for url in read_nonempty_lines(Path(file_path)):
            video_id = extract_video_id(url)
            if not video_id or video_id in processed:
                continue
            _, _, created_request = db.enqueue_video_request(
                youtube_url=url,
                youtube_video_id=video_id,
                title=None,
                language="en",
                priority=4,
                source_type="backlog_import",
                destination_type="telegram_chat",
                destination_key=f"channel:{config.TARGET_CHANNEL}",
                telegram_chat_id=config.TARGET_CHANNEL,
            )
            if created_request:
                added += 1
    log(f"backlog_import: added {added} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())