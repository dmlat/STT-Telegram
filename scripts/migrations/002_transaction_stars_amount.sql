-- Учёт фактически оплаченных Stars по строке transactions (PostgreSQL).
ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS stars_amount INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN transactions.stars_amount IS 'XTR: SuccessfulPayment.total_amount (число Stars). 0 для YooKassa и manual.';
