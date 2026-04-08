import uuid
import logging
from yookassa import Configuration, Payment
from src.config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY

_yookassa_configured = False


def _ensure_yookassa_config() -> bool:
    """Apply YooKassa credentials lazily (import-time init breaks SQLAlchemy/asyncpg DB pool)."""
    global _yookassa_configured
    if _yookassa_configured:
        return True
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        return False
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    _yookassa_configured = True
    return True


# --- Pricing: equal margin YooKassa vs Telegram Stars (see ReadMe/PROD.md) ---
# User-facing pack: 100 Stars in official Telegram purchase flow ≈ 182 ₽ (update if rate changes).
STARS_PACK_RUB = 182
STARS_RUB_PER_STAR_USER = STARS_PACK_RUB / 100  # 1.82 ₽ per Star from user wallet
STARS_RISK_FACTOR = 0.9  # buffer for TON/currency/slippage on withdrawal
STARS_EFFECTIVE_RUB_PER_STAR = STARS_RUB_PER_STAR_USER * STARS_RISK_FACTOR  # 1.638 for P&L parity
# YooKassa: acquiring 4.3% + tax 6% → net share of gross price in ₽
YOOKASSA_NET_MULTIPLIER = 1 - 0.043 - 0.06  # 0.897

# Fixed minute packs (RUB on invoice before payment fees; Stars derived via rub_price_to_stars)
TARIFF_PRICES_RUB: dict[int, int] = {
    10: 59,
    30: 159,
    60: 249,
    300: 990,
    600: 1850,
}


def rub_price_to_stars(rub: int) -> int:
    """
    Stars for XTR invoice: parity target vs YooKassa net, then round to nearest multiple of 5 (min 5 ⭐).

    Base: round(net_rub / STARS_EFFECTIVE_RUB_PER_STAR). Reference packs (₽ → ⭐): 59→30, 159→85,
    249→135, 990→540, 1850→1015.
    """
    net = rub * YOOKASSA_NET_MULTIPLIER
    raw = max(1, round(net / STARS_EFFECTIVE_RUB_PER_STAR))
    return 5 * max(1, round(raw / 5))


def get_tariff_price(minutes: int) -> int:
    """Price in RUB for a given number of minutes (fixed packs or custom formula)."""
    if minutes in TARIFF_PRICES_RUB:
        return TARIFF_PRICES_RUB[minutes]
    return int((minutes * 2.5) + 20)


def create_yookassa_payment(amount: float, description: str, return_url: str, metadata: dict = None):
    if not _ensure_yookassa_config():
        logging.error("YooKassa credentials missing")
        return None
    try:
        idempotence_key = str(uuid.uuid4())
        payment = Payment.create({
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "description": description,
            "metadata": metadata or {}
        }, idempotence_key)

        return {
            "id": payment.id,
            "confirmation_url": payment.confirmation.confirmation_url
        }
    except Exception as e:
        logging.error(f"Error creating YooKassa payment: {e}")
        return None


def check_yookassa_payment(payment_id: str):
    if not _ensure_yookassa_config():
        logging.error("YooKassa credentials missing")
        return None
    try:
        payment = Payment.find_one(payment_id)
        return payment.status
    except Exception as e:
        logging.error(f"Error checking YooKassa payment: {e}")
        return None
