from __future__ import annotations

import asyncio
import json

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app import config
from app.db import Database
from app.utils import extract_video_id, find_urls, get_youtube_metadata


router = Router()
db = Database()


@router.message(Command("start"))
async def handle_start(message: Message) -> None:
    await message.answer("Пришлите ссылку на YouTube. Я поставлю видео в общую очередь и пришлю саммари.")


@router.message(F.text | F.caption)
async def handle_link(message: Message) -> None:
    urls = find_urls(message.text or message.caption or "")
    if not urls or not message.from_user:
        return
    status_message = await message.answer("Добавляю в очередь...")
    added = 0
    duplicates = 0
    for url in urls:
        video_id = extract_video_id(url)
        if not video_id:
            continue
        meta = get_youtube_metadata(url)
        _, _, created_request = db.enqueue_video_request(
            youtube_url=url,
            youtube_video_id=video_id,
            title=meta.get("title"),
            language=None,
            priority=1,
            source_type="telegram_bot",
            destination_type="telegram_user",
            destination_key=f"tguser:{message.from_user.id}",
            telegram_user_id=message.from_user.id,
            meta_json=json.dumps({"chat_id": message.chat.id, "request_message_id": message.message_id}, ensure_ascii=False),
        )
        if created_request:
            added += 1
        else:
            duplicates += 1
    await status_message.edit_text(f"Готово. Добавлено: {added}. Уже было в очереди/обработке для вас: {duplicates}.")


async def main() -> None:
    config.ensure_dirs()
    config.validate_bot_config()
    db.init()
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    if not config.USE_WEBHOOK:
        await dp.start_polling(bot)
        return
    webhook_url = f"{config.WEBHOOK_BASE_URL.rstrip('/')}{config.WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT)
    await site.start()
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())