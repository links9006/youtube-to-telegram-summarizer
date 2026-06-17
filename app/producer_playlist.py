from __future__ import annotations

import argparse

from app import config
from app.db import Database
from app.youtube_api import fetch_playlist_video_details
from app.utils import log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["ru", "en"], required=True)
    parser.add_argument("--playlist-url", required=True)
    parser.add_argument("--source-type", required=True)
    args = parser.parse_args()
    db = Database()
    db.init()
    added = 0
    for item in fetch_playlist_video_details(args.playlist_url):
        _, _, created_request = db.enqueue_video_request(
            youtube_url=item["url"],
            youtube_video_id=item["video_id"],
            title=item.get("title"),
            language=args.language,
            priority=2,
            source_type=args.source_type,
            destination_type="telegram_chat",
            destination_key=f"channel:{config.TARGET_CHANNEL}",
            telegram_chat_id=config.TARGET_CHANNEL,
        )
        if created_request:
            added += 1
    log(f"{args.source_type}: added {added} new items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())