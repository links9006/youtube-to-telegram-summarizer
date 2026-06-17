from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web
from yt_dlp import YoutubeDL

from app import config
from app.utils import extract_video_id, get_youtube_metadata, log


INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Step1 Service</title>
  <style>
    :root {
      color-scheme: dark;
    }
    body { font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 16px; background: #0f1115; color: #e8ecf1; }
    h1 { margin-bottom: 8px; }
    form { display: flex; gap: 12px; margin: 20px 0; }
    input { flex: 1; padding: 12px; font-size: 16px; background: #171a21; color: #f3f6fb; border: 1px solid #2a3140; border-radius: 10px; }
    button { padding: 12px 18px; font-size: 16px; cursor: pointer; background: #3b82f6; color: white; border: 0; border-radius: 10px; }
    button:hover { background: #2563eb; }
    .muted { color: #96a0af; }
    .card { background: #171a21; border: 1px solid #2a3140; border-radius: 10px; padding: 16px; margin-top: 20px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #0b0d12; color: #dbe5f0; padding: 14px; border-radius: 8px; overflow: auto; border: 1px solid #232a36; }
    .error { color: #ff7b72; }
    .ok { color: #4ade80; }
    a { color: #7cb8ff; }
  </style>
</head>
<body>
  <h1>Локальный web-сервис step1</h1>
  <p class="muted">Вставьте YouTube-ссылку. Сервис скачает mp4, сделает mp3 и сохранит manifest.json. Повторно не скачивает, если кэш уже есть.</p>

  <form id="step1-form">
    <input id="url" name="url" type="url" placeholder="https://www.youtube.com/watch?v=..." required>
    <button type="submit">Запустить</button>
  </form>

  <div id="status" class="muted"></div>
  <div id="result" class="card" style="display:none;">
    <div id="summary"></div>
    <pre id="output"></pre>
  </div>

  <script>
    const form = document.getElementById('step1-form');
    const statusEl = document.getElementById('status');
    const resultEl = document.getElementById('result');
    const summaryEl = document.getElementById('summary');
    const outputEl = document.getElementById('output');

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const url = document.getElementById('url').value.trim();
      if (!url) return;

      statusEl.className = 'muted';
      statusEl.textContent = 'Обработка...';
      resultEl.style.display = 'none';

      try {
        const response = await fetch('/api/step1/process', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const data = await response.json();
        resultEl.style.display = 'block';
        outputEl.textContent = JSON.stringify(data, null, 2);

        if (!response.ok || !data.ok) {
          statusEl.className = 'error';
          statusEl.textContent = 'Ошибка';
          summaryEl.innerHTML = '<p class="error">Не удалось обработать ссылку.</p>';
          return;
        }

        const result = data.result || {};
        statusEl.className = 'ok';
        statusEl.textContent = result.cached ? 'Готово (из кэша)' : 'Готово';
        summaryEl.innerHTML = `
          <p><strong>Video ID:</strong> ${result.video_id || ''}</p>
          <p><strong>Title:</strong> ${result.title || ''}</p>
          <p><strong>MP4:</strong> ${result.files?.mp4 || ''}</p>
          <p><strong>MP3:</strong> ${result.files?.mp3 || ''}</p>
          <p><strong>TXT:</strong> ${result.files?.transcript_txt || ''}</p>
          <p><strong>1-word timings:</strong> ${result.files?.words_txt || ''}</p>
          <p><strong>2-word timings:</strong> ${result.files?.two_words_txt || ''}</p>
          <p><strong>Words:</strong> ${result.word_count || 0}</p>
          <p><strong>2-word phrases:</strong> ${result.two_word_count || 0}</p>
          <p><strong>Manifest:</strong> ${(result.files?.dir || '') + '/manifest.json'}</p>
        `;
      } catch (error) {
        resultEl.style.display = 'block';
        statusEl.className = 'error';
        statusEl.textContent = 'Ошибка сети';
        summaryEl.innerHTML = '<p class="error">Запрос к сервису не выполнился.</p>';
        outputEl.textContent = String(error);
      }
    });
  </script>
</body>
</html>
"""


def _which(binary: str) -> str | None:
    for folder in map(Path, filter(None, os.environ.get("PATH", "").split(os.pathsep))):
        candidate = folder / binary
        if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def validate_runtime() -> None:
    config.ensure_dirs()
    for binary in ("ffmpeg", "ffprobe"):
        if not _which(binary):
            raise RuntimeError(f"Required binary not found: {binary}")

    try:
        import whisper  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Whisper не установлен. Установите пакет openai-whisper.") from exc


def _probe_duration_sec(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffprobe failed")
    return round(float((proc.stdout or "").strip()), 3)


def _manifest_path(video_id: str) -> Path:
    return config.STEP1_CACHE_DIR / video_id / "manifest.json"


def _load_cached_manifest(video_id: str) -> dict[str, Any] | None:
    manifest_path = _manifest_path(video_id)
    if not manifest_path.exists():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files", {}) or {}

    required_file_keys = [
        "mp4",
        "mp3",
        "transcript_txt",
        "words_json",
        "words_txt",
        "two_words_txt",
    ]
    for key in required_file_keys:
        raw_path = str(files.get(key, "")).strip()
        if not raw_path:
            return None
        if not Path(raw_path).exists():
            return None

    if payload.get("word_count") is None or payload.get("two_word_count") is None:
        return None
    payload["cached"] = True
    return payload


def _round_ts(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _normalize_words(words: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, word in enumerate(words or [], start=1):
        token = str(word.get("word", "")).strip()
        start = _round_ts(word.get("start"))
        end = _round_ts(word.get("end"))
        if not token or start is None or end is None:
            continue
        items.append(
            {
                "index": index,
                "word": token,
                "start": start,
                "end": end,
                "probability": _round_ts(word.get("probability")),
            }
        )
    return items


def _transcribe_word_timestamps(mp3_path: Path) -> dict[str, Any]:
    import whisper

    model_name = os.environ.get("WHISPER_MODEL", "small")
    language = os.environ.get("WHISPER_LANGUAGE", "ru")
    log(f"[step1_service] whisper model={model_name} language={language}")
    model = whisper.load_model(model_name)
    return model.transcribe(
        str(mp3_path),
        language=language,
        task="transcribe",
        verbose=False,
        word_timestamps=True,
    )


def _extract_words_payload(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    words: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(result.get("segments") or [], start=1):
        for word in _normalize_words(segment.get("words")):
            words.append(
                {
                    "index": len(words) + 1,
                    "segment_index": segment_index,
                    "word": word["word"],
                    "start": word["start"],
                    "end": word["end"],
                    "probability": word["probability"],
                }
            )

    phrases: list[dict[str, Any]] = []
    for index in range(len(words) - 1):
        first = words[index]
        second = words[index + 1]
        phrases.append(
            {
                "index": index + 1,
                "text": f"{first['word']} {second['word']}",
                "start": first["start"],
                "end": second["end"],
                "words": [first["word"], second["word"]],
            }
        )
    return words, phrases


def _write_timing_outputs(work_dir: Path, mp3_path: Path, video_id: str) -> dict[str, Any]:
    words_json_path = work_dir / "words_timestamps.json"
    words_txt_path = work_dir / "words_1.txt"
    two_words_txt_path = work_dir / "words_2.txt"
    transcript_txt_path = work_dir / "transcript.txt"

    result = _transcribe_word_timestamps(mp3_path)
    words, phrases = _extract_words_payload(result)

    words_payload = {
        "video_id": video_id,
        "source_mp3": str(mp3_path),
        "language": result.get("language") or os.environ.get("WHISPER_LANGUAGE", "ru"),
        "text": str(result.get("text", "")).strip(),
        "word_count": len(words),
        "two_word_count": len(phrases),
        "words": words,
        "two_words": phrases,
    }
    words_json_path.write_text(json.dumps(words_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    transcript_txt_path.write_text(words_payload["text"] + "\n", encoding="utf-8")

    words_txt_path.write_text(
        "\n".join(f"{item['index']:04d}\t{item['start']:.3f}\t{item['end']:.3f}\t{item['word']}" for item in words) + ("\n" if words else ""),
        encoding="utf-8",
    )
    two_words_txt_path.write_text(
        "\n".join(f"{item['index']:04d}\t{item['start']:.3f}\t{item['end']:.3f}\t{item['text']}" for item in phrases) + ("\n" if phrases else ""),
        encoding="utf-8",
    )

    return {
        "transcript_txt": str(transcript_txt_path),
        "words_json": str(words_json_path),
        "words_txt": str(words_txt_path),
        "two_words_txt": str(two_words_txt_path),
        "word_count": len(words),
        "two_word_count": len(phrases),
    }


def _download_mp4(youtube_url: str, output_dir: Path, video_id: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(output_dir / f"{video_id}.%(ext)s")
    options = {
        "format": "bv*+ba/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        requested = Path(ydl.prepare_filename(info))
    final_path = output_dir / f"{video_id}.mp4"
    if final_path.exists():
        return final_path
    if requested.exists() and requested.suffix.lower() == ".mp4":
        return requested
    candidates = sorted(output_dir.glob(f"{video_id}*.mp4"))
    if candidates:
        return candidates[0]
    raise RuntimeError("Downloaded mp4 not found")


def _convert_to_mp3(mp4_path: Path, mp3_path: Path) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(mp3_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffmpeg convert failed")


def _build_manifest(video_id: str, youtube_url: str, work_dir: Path, cached: bool) -> dict[str, Any]:
    mp4_path = work_dir / f"{video_id}.mp4"
    mp3_path = work_dir / f"{video_id}.mp3"
    metadata = get_youtube_metadata(youtube_url)
    timing_payload = _write_timing_outputs(work_dir, mp3_path, video_id)
    payload = {
        "video_id": video_id,
        "youtube_url": youtube_url,
        "title": metadata.get("title") or video_id,
        "duration_sec": _probe_duration_sec(mp4_path),
        "source": "yt_dlp",
        "cached": cached,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "word_count": timing_payload["word_count"],
        "two_word_count": timing_payload["two_word_count"],
        "files": {
            "dir": str(work_dir),
            "mp4": str(mp4_path),
            "mp3": str(mp3_path),
            "transcript_txt": timing_payload["transcript_txt"],
            "words_json": timing_payload["words_json"],
            "words_txt": timing_payload["words_txt"],
            "two_words_txt": timing_payload["two_words_txt"],
        },
    }
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def process_step1(youtube_url: str) -> dict[str, Any]:
    video_id = extract_video_id(youtube_url)
    if not video_id:
        raise RuntimeError("Could not extract YouTube video id from URL")

    cached_manifest = _load_cached_manifest(video_id)
    if cached_manifest is not None:
        return cached_manifest

    work_dir = config.STEP1_CACHE_DIR / video_id
    mp4_path = work_dir / f"{video_id}.mp4"
    mp3_path = work_dir / f"{video_id}.mp3"

    if not mp4_path.exists():
        log(f"[step1_service] downloading mp4 for {video_id}")
        mp4_path = _download_mp4(youtube_url, work_dir, video_id)
    if not mp3_path.exists():
        log(f"[step1_service] converting mp3 for {video_id}")
        _convert_to_mp3(mp4_path, mp3_path)

    return _build_manifest(video_id, youtube_url, work_dir, cached=False)


async def handle_health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def handle_index(_: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html", charset="utf-8")


async def handle_step1(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    youtube_url = str(payload.get("url", "")).strip()
    if not youtube_url:
        return web.json_response({"ok": False, "error": "Field 'url' is required"}, status=400)

    try:
        # Для текущего localhost MVP выполняем шаг синхронно в том же процессе,
        # чтобы полностью исключить ошибки вида "attached to a different loop".
        result = process_step1(youtube_url)
        return web.json_response({"ok": True, "result": result})
    except Exception as exc:
        log(f"[step1_service] error: {exc}")
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


def create_app() -> web.Application:
    validate_runtime()
    app = web.Application(client_max_size=2 * 1024**2)
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/api/step1/process", handle_step1)
    return app


def main() -> int:
    app = create_app()
    log(f"[step1_service] listening on http://{config.STEP1_SERVICE_HOST}:{config.STEP1_SERVICE_PORT}")
    web.run_app(app, host=config.STEP1_SERVICE_HOST, port=config.STEP1_SERVICE_PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())