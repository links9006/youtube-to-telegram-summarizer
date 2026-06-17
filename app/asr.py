from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app import config


_GIGAAM_MODEL = None


def _audio_duration_sec(input_audio: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(input_audio)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffprobe failed")
    return float((proc.stdout or "").strip())


def _load_gigaam_model():
    global _GIGAAM_MODEL
    if _GIGAAM_MODEL is not None:
        return _GIGAAM_MODEL
    import gigaam

    if config.HUGGINGFACE_API_KEY:
        os.environ["HF_TOKEN"] = config.HUGGINGFACE_API_KEY
    _GIGAAM_MODEL = gigaam.load_model("rnnt")
    return _GIGAAM_MODEL


def _extract_text(result: object) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        if isinstance(result.get("text"), str):
            return result["text"].strip()
        segments = result.get("segments")
        if isinstance(segments, list):
            return " ".join(str(item.get("text", "")).strip() for item in segments if isinstance(item, dict)).strip()
    if isinstance(result, list):
        return " ".join(_extract_text(item) for item in result).strip()
    return str(result).strip()


def _gigaam_chunked(model, input_audio: Path, segment_seconds: int = 30) -> str:
    with tempfile.TemporaryDirectory(prefix="gigaam_chunks_") as tmp_dir:
        pattern = Path(tmp_dir) / "chunk_%04d.wav"
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(input_audio), "-map", "0:a", "-f", "segment", "-segment_time", str(segment_seconds),
                "-reset_timestamps", "1", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(pattern),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffmpeg split failed")
        chunks = [path for path in sorted(Path(tmp_dir).glob("chunk_*.wav")) if path.stat().st_size > 1024]
        texts: list[str] = []
        for chunk in chunks:
            try:
                texts.append(_extract_text(model.transcribe(str(chunk))))
            except Exception as exc:
                if "too long" in str(exc).lower() and segment_seconds > 5:
                    texts.append(_gigaam_chunked(model, chunk, segment_seconds=max(segment_seconds // 2, 5)))
                else:
                    raise
        return "\n".join(item for item in texts if item).strip()


def transcribe_ru(mp3_path: Path) -> str:
    model = _load_gigaam_model()
    duration = _audio_duration_sec(mp3_path)
    if duration > 30 and hasattr(model, "transcribe_longform"):
        try:
            result = model.transcribe_longform(str(mp3_path))
            return "\n".join(item.get("transcription", "") for item in result if isinstance(item, dict)).strip()
        except Exception:
            return _gigaam_chunked(model, mp3_path, segment_seconds=config.GIGAAM_CHUNK_SECONDS)
    if duration > 30:
        return _gigaam_chunked(model, mp3_path, segment_seconds=config.GIGAAM_CHUNK_SECONDS)
    try:
        return _extract_text(model.transcribe(str(mp3_path)))
    except Exception as exc:
        if "too long" in str(exc).lower():
            if hasattr(model, "transcribe_longform"):
                try:
                    result = model.transcribe_longform(str(mp3_path))
                    return "\n".join(item.get("transcription", "") for item in result if isinstance(item, dict)).strip()
                except Exception:
                    return _gigaam_chunked(model, mp3_path, segment_seconds=max(config.GIGAAM_CHUNK_SECONDS // 2, 10))
            return _gigaam_chunked(model, mp3_path, segment_seconds=max(config.GIGAAM_CHUNK_SECONDS // 2, 10))
        raise


def _find_whisper_cli() -> str | None:
    candidate = Path(sys.executable).resolve().parent / "whisper"
    if candidate.exists():
        return str(candidate)
    return None


def transcribe_en(mp3_path: Path) -> str:
    errors: list[str] = []
    whisper_cli = _find_whisper_cli()
    for model_name in config.WHISPER_MODELS:
        with tempfile.TemporaryDirectory(prefix="whisper_") as tmp_dir:
            if whisper_cli:
                cmd = [whisper_cli, str(mp3_path), "--model", model_name, "--language", "en", "--task", "transcribe", "--output_format", "txt", "--output_dir", tmp_dir]
            else:
                cmd = [sys.executable, "-m", "whisper", str(mp3_path), "--model", model_name, "--language", "en", "--task", "transcribe", "--output_format", "txt", "--output_dir", tmp_dir]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                generated = Path(tmp_dir) / f"{mp3_path.stem}.txt"
                if generated.exists():
                    return generated.read_text(encoding="utf-8").strip()
            details = (proc.stderr or proc.stdout or f"returncode={proc.returncode}").strip()
            errors.append(f"{model_name}: {details[:300]}")
    raise RuntimeError("Whisper failed: " + " | ".join(errors))


def transcribe_audio(mp3_path: Path, language: str) -> str:
    if language == "ru":
        return transcribe_ru(mp3_path)
    return transcribe_en(mp3_path)