import uuid
import logging
from yookassa import Configuration, Payment
from src.config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY

# Initialize YooKassa
if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY

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
    Stars count for invoice (XTR) so planned net revenue matches YooKassa net after fees.

    Uses round(); switch to math.ceil for a margin-favorable (higher Stars) policy.
    Reference grid: 59→32, 159→87, 249→136, 990→542, 1850→1013.
    """
    net = rub * YOOKASSA_NET_MULTIPLIER
    stars = round(net / STARS_EFFECTIVE_RUB_PER_STAR)
    return max(1, stars)


def get_tariff_price(minutes: int) -> int:
    """Price in RUB for a given number of minutes (fixed packs or custom formula)."""
    if minutes in TARIFF_PRICES_RUB:
        return TARIFF_PRICES_RUB[minutes]
    return int((minutes * 2.5) + 20)


def create_yookassa_payment(amount: float, description: str, return_url: str, metadata: dict = None):
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
    try:
        payment = Payment.find_one(payment_id)
        return payment.status
    except Exception as e:
        logging.error(f"Error checking YooKassa payment: {e}")
        return None
