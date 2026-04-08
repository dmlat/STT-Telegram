"""Stars XTR invoice payload (no heavy payment deps — safe for unit tests)."""


def parse_stars_invoice_payload(payload: str) -> tuple[int, float]:
    """
    Parse invoice_payload from Stars checkout: buy_{minutes}_{amount_rub}.
    Uses split("_", 2) so extra underscores in a suffix do not break parsing.
    """
    if not payload or not payload.startswith("buy_"):
        raise ValueError("payload must start with buy_")
    parts = payload.split("_", 2)
    if len(parts) != 3:
        raise ValueError("payload must have buy, minutes, and rub segments")
    _, minutes_s, rub_s = parts
    return int(minutes_s), float(rub_s)
