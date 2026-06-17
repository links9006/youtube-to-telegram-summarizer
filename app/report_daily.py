from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path

from app import config
from app.db import Database


def _fmt_dt(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("T", " ")


def _html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; background: #f8fafc; }}
    h1, h2, h3 {{ color: #111827; }}
    .muted {{ color: #6b7280; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
    .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
    .card .label {{ font-size: 12px; color: #6b7280; text-transform: uppercase; }}
    .card .value {{ font-size: 26px; font-weight: bold; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0 24px; background: white; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .section {{ margin-top: 28px; }}
    .small {{ font-size: 12px; }}
    .ok {{ color: #065f46; }}
    .warn {{ color: #92400e; }}
    .bad {{ color: #991b1b; }}
    code {{ background: #eef2ff; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _fetch_rows(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    thead = "".join(f"<th>{escape(header)}</th>" for header in headers)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"


def build_report_html(report_day: date) -> str:
    start = datetime.combine(report_day, time.min)
    end = start + timedelta(days=1)
    db = Database()
    with db.connect() as conn:
        conn.row_factory = sqlite3.Row
        params = (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))

        requests_created = _fetch_rows(
            conn,
            """
            SELECT r.*, v.youtube_video_id, v.youtube_url, v.title, v.language, v.status, v.error_text,
                   v.created_at AS video_created_at, v.asr_started_at, v.summary_started_at, v.completed_at
            FROM requests r
            JOIN videos v ON v.id = r.video_id
            WHERE r.created_at >= ? AND r.created_at < ?
            ORDER BY r.created_at ASC, r.id ASC
            """,
            params,
        )
        videos_created = _fetch_rows(
            conn,
            "SELECT * FROM videos WHERE created_at >= ? AND created_at < ? ORDER BY created_at ASC, id ASC",
            params,
        )
        videos_completed = _fetch_rows(
            conn,
            "SELECT * FROM videos WHERE completed_at >= ? AND completed_at < ? ORDER BY completed_at ASC, id ASC",
            params,
        )
        videos_failed = _fetch_rows(
            conn,
            "SELECT * FROM videos WHERE updated_at >= ? AND updated_at < ? AND status = 'failed' ORDER BY updated_at ASC, id ASC",
            params,
        )
        delivered_requests = _fetch_rows(
            conn,
            "SELECT * FROM requests WHERE delivered_at >= ? AND delivered_at < ? ORDER BY delivered_at ASC, id ASC",
            params,
        )

    created_source_counter = Counter(row["source_type"] for row in requests_created)
    created_priority_counter = Counter(str(row["priority"]) for row in requests_created)
    video_lang_counter = Counter((row["language"] or "unknown") for row in videos_created)
    video_status_counter = Counter(row["status"] for row in videos_created)
    completed_lang_counter = Counter((row["language"] or "unknown") for row in videos_completed)
    bot_requests = [row for row in requests_created if row["source_type"] == "telegram_bot"]
    bot_users = Counter(str(row["telegram_user_id"] or "unknown") for row in bot_requests)
    bot_statuses = Counter(row["status"] for row in bot_requests)
    bot_languages = Counter((row["language"] or "unknown") for row in bot_requests)

    overview_cards = [
        ("Дата отчёта", report_day.isoformat()),
        ("Новых видео", str(len(videos_created))),
        ("Новых запросов", str(len(requests_created))),
        ("Завершено", str(len(videos_completed))),
        ("Ошибок", str(len(videos_failed))),
        ("Доставок", str(len(delivered_requests))),
        ("Bot requests", str(len(bot_requests))),
        ("Bot users", str(len(bot_users))),
    ]
    cards_html = "".join(
        f'<div class="card"><div class="label">{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        for label, value in overview_cards
    )

    source_rows = [[escape(source), str(count)] for source, count in created_source_counter.most_common()]
    priority_rows = [[priority, str(count)] for priority, count in sorted(created_priority_counter.items())]
    lang_rows = [[escape(lang), str(count)] for lang, count in video_lang_counter.most_common()]
    completed_lang_rows = [[escape(lang), str(count)] for lang, count in completed_lang_counter.most_common()]
    status_rows = [[escape(status), str(count)] for status, count in video_status_counter.most_common()]

    bot_user_rows: list[list[str]] = []
    for user_id, count in bot_users.most_common(50):
        user_rows = [row for row in bot_requests if str(row["telegram_user_id"] or "unknown") == user_id]
        completed = sum(1 for row in user_rows if row["status"] == "done")
        failed = sum(1 for row in user_rows if row["status"] == "failed")
        pending = sum(1 for row in user_rows if row["delivered_at"] is None)
        bot_user_rows.append([user_id, str(count), str(completed), str(failed), str(pending)])

    bot_detail_rows: list[list[str]] = []
    for row in bot_requests[:500]:
        meta = ""
        if row["meta_json"]:
            try:
                meta_obj = json.loads(row["meta_json"])
                meta = ", ".join(f"{key}={value}" for key, value in meta_obj.items())
            except Exception:
                meta = str(row["meta_json"])
        status_class = "ok" if row["status"] == "done" else "bad" if row["status"] == "failed" else "warn"
        title = escape(row["title"] or row["youtube_video_id"])
        bot_detail_rows.append(
            [
                escape(_fmt_dt(row["created_at"])),
                escape(str(row["telegram_user_id"] or "unknown")),
                f'<code>{escape(row["youtube_video_id"])}</code>',
                title,
                escape(row["language"] or "unknown"),
                f'<span class="{status_class}">{escape(row["status"])}</span>',
                escape(_fmt_dt(row["delivered_at"])),
                escape(meta or "—"),
            ]
        )

    failed_rows = [
        [
            f'<code>{escape(row["youtube_video_id"])}</code>',
            escape(row["title"] or "—"),
            escape(row["language"] or "unknown"),
            escape(_fmt_dt(row["updated_at"])),
            escape((row["error_text"] or "")[:400] or "—"),
        ]
        for row in videos_failed
    ]

    completed_rows = [
        [
            f'<code>{escape(row["youtube_video_id"])}</code>',
            escape(row["title"] or "—"),
            escape(row["language"] or "unknown"),
            escape(_fmt_dt(row["created_at"])),
            escape(_fmt_dt(row["completed_at"])),
        ]
        for row in videos_completed[:300]
    ]

    body = f"""
<h1>Daily report: {escape(report_day.isoformat())}</h1>
<p class="muted">Отчёт автоматически собран за прошлые сутки по SQLite БД all-youtube. Вверху — краткий обзор, ниже — подробная разбивка, особенно по взаимодействию с Telegram-ботом.</p>

<div class="cards">{cards_html}</div>

<div class="section">
  <h2>Краткий обзор</h2>
  <h3>Новые запросы по источникам</h3>
  {_render_table(["Источник", "Кол-во"], source_rows or [["—", "0"]])}
  <h3>Новые запросы по приоритетам</h3>
  {_render_table(["Priority", "Кол-во"], priority_rows or [["—", "0"]])}
  <h3>Новые видео по языкам</h3>
  {_render_table(["Язык", "Кол-во"], lang_rows or [["—", "0"]])}
  <h3>Новые видео по статусам</h3>
  {_render_table(["Статус", "Кол-во"], status_rows or [["—", "0"]])}
  <h3>Завершённые видео по языкам</h3>
  {_render_table(["Язык", "Кол-во"], completed_lang_rows or [["—", "0"]])}
</div>

<div class="section">
  <h2>Подробно: взаимодействие с ботом</h2>
  <p><strong>Bot requests:</strong> {len(bot_requests)} &nbsp; | &nbsp; <strong>Уникальных users:</strong> {len(bot_users)} &nbsp; | &nbsp; <strong>Статусы:</strong> {escape(', '.join(f'{k}={v}' for k, v in bot_statuses.items()) or 'нет')} &nbsp; | &nbsp; <strong>Языки:</strong> {escape(', '.join(f'{k}={v}' for k, v in bot_languages.items()) or 'нет')}</p>
  <h3>Пользователи бота и объёмы</h3>
  {_render_table(["Telegram user id", "Запросов", "Done", "Failed", "Pending delivery"], bot_user_rows or [["—", "0", "0", "0", "0"]])}
  <h3>Детальный список bot-request'ов</h3>
  <p class="small muted">Показываются первые 500 записей за день в порядке создания.</p>
  {_render_table(["Создан", "User", "Video ID", "Title", "Lang", "Status", "Delivered", "Meta"], bot_detail_rows or [["—", "—", "—", "—", "—", "—", "—", "—"]])}
</div>

<div class="section">
  <h2>Ошибки за день</h2>
  {_render_table(["Video ID", "Title", "Lang", "Когда", "Ошибка"], failed_rows or [["—", "—", "—", "—", "Ошибок нет"]])}
</div>

<div class="section">
  <h2>Успешно завершённые видео</h2>
  <p class="small muted">Показываются первые 300 завершённых видео за отчётные сутки.</p>
  {_render_table(["Video ID", "Title", "Lang", "Создано", "Завершено"], completed_rows or [["—", "—", "—", "—", "Нет завершённых видео"]])}
</div>
"""
    return _html_page(f"all-youtube daily report {report_day.isoformat()}", body)


def main() -> int:
    config.ensure_dirs()
    report_day = datetime.now().date() - timedelta(days=1)
    html = build_report_html(report_day)
    report_path = config.LOG_DIR / f"daily-report-{report_day.isoformat()}.html"
    report_path.write_text(html, encoding="utf-8")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())