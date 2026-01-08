import uuid
import logging
from yookassa import Configuration, Payment
from src.config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY

# Initialize YooKassa
if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY

def get_tariff_price(minutes: int) -> int:
    """Returns price in RUB for a given number of minutes."""
    # Fixed tariffs
    tariffs = {
        10: 49,
        30: 129,
        60: 199,
        300: 790,
        600: 1490
    }
    
    if minutes in tariffs:
        return tariffs[minutes]
    
    # Custom formula: (Minutes * 2.5) + 20, rounded to integer
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

