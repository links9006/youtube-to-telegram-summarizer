from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def has_cyrillic(text: str | None) -> bool:
    return bool(CYRILLIC_RE.search(text or ""))


def find_urls(text: str) -> list[str]:
    return [match.group(0).strip() for match in URL_RE.finditer(text or "")]


def extract_video_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")
    if host == "youtu.be" and path:
        return path.split("/")[0]
    if host.endswith("youtube.com"):
        query = urllib.parse.parse_qs(parsed.query)
        value = query.get("v", [None])[0]
        if value:
            return value
        if path.startswith("shorts/"):
            return path.split("/", 1)[1] or None
    return None


def split_for_telegram(text: str, chunk_size: int = 3500) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    lines = text.splitlines()
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line
        while len(current) > chunk_size:
            chunks.append(current[:chunk_size])
            current = current[chunk_size:]
    if current:
        chunks.append(current)
    return chunks


def get_youtube_metadata(url: str) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return {"title": None, "duration": 0}
        return json.loads(proc.stdout)
    except Exception:
        return {"title": None, "duration": 0}


def read_nonempty_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]