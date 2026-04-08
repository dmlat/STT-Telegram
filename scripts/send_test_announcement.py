#!/usr/bin/env python3
"""
Отправка объявления только тестовому пользователю (280186359).
Не делает массовую рассылку.

Запуск с корня репозитория (нужен BOT_TOKEN в .env или в окружении):

  python scripts/send_test_announcement.py

Если у бота в Telegram всё ещё включён webhook, long polling в контейнере
не получает входящие обновления — бот «молчит». Тогда:

  python scripts/send_test_announcement.py --delete-webhook

(снимет webhook; после этого перезапустите контейнер с ботом на polling).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

BROADCAST_TEST_USER_ID = 280186359
ANNOUNCEMENT_TEXT = (
    "Теперь доступны пакеты минут для расшифровки голоса в текст. Спасибо за ожидание."
)


def _api(method: str, payload: dict, token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description="Send announcement only to test Telegram id.")
    parser.add_argument(
        "--delete-webhook",
        action="store_true",
        help="Call deleteWebhook (fixes silent bot if webhook was left enabled).",
    )
    args = parser.parse_args()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: BOT_TOKEN is empty — set it in .env or environment.", file=sys.stderr)
        sys.exit(1)

    try:
        info = _api("getWebhookInfo", {}, token)
        wh = info.get("result") or {}
        wh_url = wh.get("url") or ""
        if wh_url:
            print(f"Warning: webhook is set to {wh_url!r} — polling will not receive updates.")
            if not args.delete_webhook:
                print("Re-run with --delete-webhook to remove it, then restart the bot container.")
            else:
                del_r = _api("deleteWebhook", {"drop_pending_updates": False}, token)
                print("deleteWebhook:", del_r.get("ok", del_r))

        if args.delete_webhook and not wh_url:
            print("No webhook URL; nothing to delete.")

        r = _api(
            "sendMessage",
            {"chat_id": BROADCAST_TEST_USER_ID, "text": ANNOUNCEMENT_TEXT},
            token,
        )
        if not r.get("ok"):
            print("sendMessage failed:", r, file=sys.stderr)
            sys.exit(1)
        print(f"OK: sent to chat_id={BROADCAST_TEST_USER_ID}")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
