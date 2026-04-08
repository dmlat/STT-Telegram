-- Stars refund + FIFO: new columns on transactions (PostgreSQL).
-- Run once on prod before deploying code that uses these fields.
-- Review backfill: only safe if balances were not partially spent from legacy rows;
-- otherwise leave seconds_remaining at 0 for old rows and rely on new purchases only.

ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS seconds_remaining DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS invoice_payload VARCHAR;

ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS stars_refund_status VARCHAR NOT NULL DEFAULT 'none';

-- Optional backfill for historical successful purchases (see ReadMe/PROD.md risks):
-- UPDATE transactions
-- SET seconds_remaining = seconds_added
-- WHERE status = 'success' AND provider IN ('telegram_stars', 'yookassa') AND seconds_remaining = 0;
