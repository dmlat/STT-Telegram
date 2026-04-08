"""Unit tests for Stars invoice payload parsing."""
import pytest

from src.services.stars_invoice import parse_stars_invoice_payload


def test_parse_custom_5_min():
    assert parse_stars_invoice_payload("buy_5_32") == (5, 32.0)


def test_parse_fixed_pack():
    assert parse_stars_invoice_payload("buy_10_59") == (10, 59.0)
    assert parse_stars_invoice_payload("buy_600_1850") == (600, 1850.0)


def test_invalid_prefix():
    with pytest.raises(ValueError):
        parse_stars_invoice_payload("pay_5_32")


def test_too_few_segments():
    with pytest.raises(ValueError):
        parse_stars_invoice_payload("buy_5")
