from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from app import config
from app.asr import transcribe_audio
from app.db import Database
from app.telethon_downloader import TopsaversClient
from app.utils import log


async def main() -> None:
    config.ensure_dirs()
    config.validate_worker_config()
    db = Database()
    db.init()
    downloader = TopsaversClient()
    try:
        await downloader.connect()
    except Exception as exc:
        # Don't crash the worker on startup: it will self-heal via ensure_connected().
        log(f"initial Telegram connect failed, will retry in loop: {exc}")
    try:
        while True:
            job = db.claim_next_for_asr()
            if not job:
                await asyncio.sleep(3)
                continue
            workdir = Path(tempfile.mkdtemp(prefix=f"all_youtube_{job.youtube_video_id}_", dir=str(config.DOWNLOAD_DIR)))
            mp3_path: Path | None = None
            try:
                log(f"ASR start {job.youtube_video_id}")
                mp3_path, detected_language = await downloader.download_audio(job.youtube_url, workdir)
                language = job.language or detected_language
                db.update_video_language(job.id, language)
                transcript = transcribe_audio(mp3_path, language)
                (config.TRANSCRIPTS_DIR / f"{job.youtube_video_id}.txt").write_text(transcript, encoding="utf-8")
                db.set_transcript(job.id, transcript)
                log(f"ASR done {job.youtube_video_id} language={language} chars={len(transcript)}")
            except Exception as exc:
                db.fail_video(job.id, str(exc))
                log(f"ASR failed {job.youtube_video_id}: {exc}")
            finally:
                if mp3_path:
                    mp3_path.unlink(missing_ok=True)
                shutil.rmtree(workdir, ignore_errors=True)
    finally:
        await downloader.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
