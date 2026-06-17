from __future__ import annotations

from app import config
from app.db import Database
from app.youtube_api import search_today_videos
from app.utils import log


def main() -> int:
    db = Database()
    db.init()
    added = 0
    for query in config.SEARCH_QUERIES:
        for item in search_today_videos(query):
            _, _, created_request = db.enqueue_video_request(
                youtube_url=item["url"],
                youtube_video_id=item["video_id"],
                title=item.get("title"),
                language="en",
                priority=3,
                source_type="daily_search",
                destination_type="telegram_chat",
                destination_key=f"channel:{config.TARGET_CHANNEL}",
                telegram_chat_id=config.TARGET_CHANNEL,
            )
            if created_request:
                added += 1
    log(f"daily_search: added {added} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())