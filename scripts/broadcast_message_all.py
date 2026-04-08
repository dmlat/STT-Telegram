#!/usr/bin/env python3
"""
Разовая рассылка всем user id из БД (как /broadcast в боте).
Запуск в контейнере бота:

  docker compose exec -T bot python /app/scripts/broadcast_message_all.py

Текст задаётся константой ниже или переменной окружения BROADCAST_TEXT (переопределяет константу).
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = "/app"
if os.path.isdir(ROOT):
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from src.config import BOT_TOKEN
from src.services.db_service import get_all_user_ids, init_db

# Текст по умолчанию (можно переопределить BROADCAST_TEXT)
DEFAULT_TEXT = (
    "В боте появилась возможность купить пакеты минут для расшифровки голоса в текст за Telegram Stars.\n\n"
    "Для пользователей из РФ купить Stars можно картой в официальном боте Telegram\n\n"
    "@PremiumBot\n\n"
    "Спасибо за ожидание ❤️"
)


async def main() -> None:
    text = (os.environ.get("BROADCAST_TEXT") or "").strip() or DEFAULT_TEXT
    if not BOT_TOKEN:
        print("BOT_TOKEN is empty", file=sys.stderr)
        sys.exit(1)

    await init_db()
    user_ids = await get_all_user_ids()
    bot = Bot(token=BOT_TOKEN)
    ok, fail = 0, 0
    try:
        for uid in user_ids:
            try:
                await bot.send_message(uid, text)
                ok += 1
            except TelegramForbiddenError:
                fail += 1
            except Exception as e:
                fail += 1
                print(f"fail uid={uid}: {e}", file=sys.stderr)
            await asyncio.sleep(0.05)
    finally:
        await bot.session.close()

    print(f"Отправлено: {ok}, ошибок/пропусков: {fail}, всего в базе: {len(user_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
