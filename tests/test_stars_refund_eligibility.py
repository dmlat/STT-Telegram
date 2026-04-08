"""Refund eligibility rules (no DB)."""
from types import SimpleNamespace

from src.services.stars_refund_service import _eligible_for_stars_refund


def test_ok_full_unused():
    tx = SimpleNamespace(
        provider="telegram_stars",
        status="success",
        stars_refund_status="none",
        payment_id="chg1",
        seconds_remaining=300.0,
        seconds_added=300.0,
    )
    ok, err = _eligible_for_stars_refund(tx)
    assert ok and err == ""


def test_reject_partially_used():
    tx = SimpleNamespace(
        provider="telegram_stars",
        status="success",
        stars_refund_status="none",
        payment_id="chg1",
        seconds_remaining=100.0,
        seconds_added=300.0,
    )
    ok, err = _eligible_for_stars_refund(tx)
    assert not ok
    assert "частично" in err.lower()


def test_reject_yookassa():
    tx = SimpleNamespace(
        provider="yookassa",
        status="success",
        stars_refund_status="none",
        payment_id="p1",
        seconds_remaining=60.0,
        seconds_added=60.0,
    )
    ok, err = _eligible_for_stars_refund(tx)
    assert not ok
