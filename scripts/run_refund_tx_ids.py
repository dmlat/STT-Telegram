"""One-off: refund Stars by transaction ids (run in bot container)."""
import asyncio
import os
import sys

os.chdir("/app")
sys.path.insert(0, "/app")


async def main():
    from aiogram import Bot

    from src.config import BOT_TOKEN
    from src.services.stars_refund_service import refund_telegram_stars_by_tx_id

    raw = os.environ.get("REFUND_TX_IDS", "")
    ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not ids:
        print("Set REFUND_TX_IDS=1,2,3")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    try:
        for tx_id in ids:
            ok, text = await refund_telegram_stars_by_tx_id(bot, tx_id)
            print(f"tx_id={tx_id} ok={ok} {text}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
