from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app import config


def _get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"YouTube API HTTP {exc.code}: {body}") from exc


def extract_playlist_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    value = urllib.parse.parse_qs(parsed.query).get("list", [None])[0]
    if not value:
        raise RuntimeError("playlist id not found in url")
    return value


def fetch_playlist_video_details(playlist_url: str) -> list[dict]:
    playlist_id = extract_playlist_id(playlist_url)
    results: list[dict] = []
    page_token: str | None = None
    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": config.YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _get_json(f"https://www.googleapis.com/youtube/v3/playlistItems?{urllib.parse.urlencode(params)}")
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId") or item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            results.append(
                {
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": snippet.get("title") or video_id,
                    "published_at": snippet.get("publishedAt") or "",
                }
            )
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return results


def search_today_videos(query: str) -> list[dict]:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": today_start.isoformat().replace("+00:00", "Z"),
        "maxResults": config.SEARCH_MAX_RESULTS,
        "relevanceLanguage": "en",
        "key": config.YOUTUBE_API_KEY,
    }
    payload = _get_json(f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(params)}")
    results: list[dict] = []
    for item in payload.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        results.append(
            {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title") or video_id,
                "published_at": snippet.get("publishedAt") or "",
                "query": query,
            }
        )
    return results