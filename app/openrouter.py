from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request

from app import config


def build_summary_prompt(title: str, url: str, transcript: str) -> str:
    clipped = transcript.strip()
    if len(clipped) > config.MAX_TRANSCRIPT_CHARS:
        clipped = clipped[: config.MAX_TRANSCRIPT_CHARS] + "\n\n[ОБРЕЗАНО]"
    return (
        "Ниже дан транскрипт YouTube-видео. Составь итоговое саммари полностью на русском языке.\n"
        "Структура:\n"
        "1) Короткое резюме.\n"
        "2) Главные тезисы списком.\n"
        "3) Практические выводы / инструменты / цифры, если они есть.\n"
        "Игнорируй рекламу, приветствия и повторы.\n"
        f"Название: {title}\n"
        f"Ссылка: {url}\n\n"
        f"Транскрипт:\n<<<\n{clipped}\n>>>"
    )


def summarize_video(title: str, url: str, transcript: str) -> str:
    models = config.OPENROUTER_MODELS[:]
    random.shuffle(models)
    prompt = build_summary_prompt(title, url, transcript)
    last_error: Exception | None = None
    for index, model in enumerate(models, start=1):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Ты аккуратный аналитик и делаешь качественные русскоязычные саммари."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            config.OPENROUTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            text = content if isinstance(content, str) else str(content)
            return f"{text.strip()}\n\nИсточник: {url}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            last_error = RuntimeError(f"OpenRouter HTTP {exc.code}: {body[:500]}")
        except Exception as exc:
            last_error = exc
        if index < len(models):
            time.sleep(2)
    raise RuntimeError(f"OpenRouter failed: {last_error}")


def build_digest_prompt(source_text: str, post_url: str) -> str:
    clipped = source_text.strip()
    if len(clipped) > 24000:
        clipped = clipped[:24000] + "\n\n[ОБРЕЗАНО]"
    return (
        "Ниже дан текст саммари-поста из Telegram-канала. "
        "Сделай очень короткий дайджест полностью на русском языке в JSON формате.\n"
        "Нужны поля: title, description.\n"
        "title: 2-10 слов, без кавычек, цепляющий, но без кликбейта.\n"
        "description: 1-2 предложения, кратко передай суть и пользу.\n"
        "Верни только валидный JSON без markdown.\n"
        f"Ссылка на исходный пост: {post_url}\n\n"
        f"Текст поста:\n<<<\n{clipped}\n>>>"
    )


def summarize_digest_post(source_text: str, post_url: str) -> tuple[str, str]:
    models = config.OPENROUTER_MODELS[:]
    random.shuffle(models)
    prompt = build_digest_prompt(source_text, post_url)
    last_error: Exception | None = None
    for index, model in enumerate(models, start=1):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Ты редактор Telegram-дайджеста и возвращаешь только JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            config.OPENROUTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            text = content if isinstance(content, str) else str(content)
            parsed = json.loads(text)
            title = str(parsed.get("title", "")).strip()
            description = str(parsed.get("description", "")).strip()
            if not title or not description:
                raise RuntimeError("Digest JSON missing title or description")
            return title, description
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            last_error = RuntimeError(f"OpenRouter HTTP {exc.code}: {body[:500]}")
        except Exception as exc:
            last_error = exc
        if index < len(models):
            time.sleep(2)
    raise RuntimeError(f"OpenRouter digest failed: {last_error}")