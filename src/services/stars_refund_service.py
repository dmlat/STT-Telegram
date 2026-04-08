"""Telegram Stars refunds via Bot API refundStarPayment + DB consistency."""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy import select

from src.services.db_service import (
    Transaction,
    User,
    async_session,
    get_transaction,
    get_transaction_by_payment_id,
)


def _eligible_for_stars_refund(tx: Transaction | None) -> tuple[bool, str]:
    if not tx:
        return False, "Транзакция не найдена."
    if tx.provider != "telegram_stars":
        return False, "Возврат Stars только для оплат telegram_stars."
    if tx.status != "success":
        return False, f"Недопустимый статус транзакции: {tx.status}."
    if tx.stars_refund_status == "refunded":
        return False, "Этот платёж уже помечен как возвращённый."
    if not tx.payment_id:
        return False, "Нет telegram_payment_charge_id в записи."
    if tx.seconds_remaining < tx.seconds_added:
        return (
            False,
            "Пакет уже частично израсходован; Telegram не поддерживает частичный refund Stars.",
        )
    return True, ""


async def finalize_stars_refund_in_db(tx_id: int) -> tuple[bool, str]:
    """After Telegram confirms refund: deduct balance and mark tx."""
    async with async_session() as session:
        stmt = select(Transaction).where(Transaction.id == tx_id).with_for_update()
        tx = (await session.execute(stmt)).scalar_one_or_none()
        if not tx:
            await session.rollback()
            return False, "Транзакция не найдена."
        if tx.stars_refund_status == "refunded":
            await session.rollback()
            return True, ""
        ok, err = _eligible_for_stars_refund(tx)
        if not ok:
            await session.rollback()
            return False, err
        ustmt = select(User).where(User.id == tx.user_id).with_for_update()
        user = (await session.execute(ustmt)).scalar_one_or_none()
        if not user:
            await session.rollback()
            return False, "Пользователь не найден в БД."
        claw = tx.seconds_remaining
        user.balance_seconds = max(0.0, user.balance_seconds - claw)
        tx.seconds_remaining = 0.0
        tx.stars_refund_status = "refunded"
        await session.commit()
        return True, ""


async def refund_telegram_stars_by_tx_id(bot: Bot, tx_id: int) -> tuple[bool, str]:
    """Full Stars refund for one transaction (unused package only)."""
    tx = await get_transaction(tx_id)
    ok, err = _eligible_for_stars_refund(tx)
    if not ok:
        return False, err
    assert tx is not None
    try:
        tg_ok = await bot.refund_star_payment(
            user_id=tx.user_id,
            telegram_payment_charge_id=tx.payment_id,
        )
    except Exception as e:
        err_s = str(e)
        if "CHARGE_ALREADY_REFUNDED" in err_s or "already been refunded" in err_s.lower():
            logging.warning("refundStarPayment: already refunded tx_id=%s: %s", tx_id, e)
            tg_ok = True
        else:
            logging.exception("refundStarPayment failed tx_id=%s", tx_id)
            async with async_session() as session:
                t2 = await session.get(Transaction, tx_id)
                if t2:
                    t2.stars_refund_status = "failed"
                    await session.commit()
            return False, f"Ошибка Telegram: {e}"

    if not tg_ok:
        return False, "Telegram вернул неуспех для refundStarPayment."

    ok_db, err_db = await finalize_stars_refund_in_db(tx_id)
    if not ok_db:
        logging.error(
            "DB finalize after successful Telegram refund failed tx_id=%s: %s",
            tx_id,
            err_db,
        )
        return False, err_db
    return True, "Возврат Stars выполнен, баланс обновлён."


async def refund_telegram_stars_by_charge_id(bot: Bot, user_id: int, charge_id: str) -> tuple[bool, str]:
    """Lookup tx by user_id + telegram_payment_charge_id, then same as by_tx_id."""
    tx = await get_transaction_by_payment_id(user_id, charge_id)
    if not tx:
        return (
            False,
            "Транзакция с таким charge_id не найдена. Нужна строка в БД (или создайте вручную).",
        )
    return await refund_telegram_stars_by_tx_id(bot, tx.id)
