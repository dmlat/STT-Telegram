"""One-off: credit admin seconds (run inside container: python scripts/run_admin_credit_once.py)."""
import asyncio
import os
import sys

os.chdir("/app")
sys.path.insert(0, "/app")


async def main():
    from sqlalchemy import text

    from src.services.db_service import add_balance_seconds, init_db, async_session

    await init_db()
    uid = int(os.environ.get("ADMIN_CREDIT_USER_ID", "280186359"))
    seconds = float(os.environ.get("ADMIN_CREDIT_SECONDS", "300"))
    ok = await add_balance_seconds(uid, seconds)
    print("add_balance_seconds", ok, "uid", uid, "seconds", seconds)
    async with async_session() as session:
        r = await session.execute(
            text("SELECT balance_seconds FROM users WHERE id = :uid"), {"uid": uid}
        )
        print("balance_after", r.scalar())


if __name__ == "__main__":
    asyncio.run(main())
