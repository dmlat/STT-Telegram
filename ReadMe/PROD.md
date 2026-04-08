# Прод: тарифы, Stars, рассылка

## Модель «одинаковая маржа на пакет»

- **Себестоимость API:** 0,6 ₽ / мин (ориентир: $0,006 × 100 ₽/$).
- **YooKassa:** с выручки −4,3% эквайринг и −6% налог → множитель **0,897** к цене в ₽ (чистая выручка бизнеса в модели).
- **Stars:** в официальном потоке покупки у Telegram **100 ⭐ ≈ 182 ₽** → 1,82 ₽ / ⭐ «из кошелька пользователя». Для P&L и сопоставления с YooKassa в коде заложен буфер **10%** на вывод/курс: эффективно **1,638 ₽** на 1 ⭐, зачисленную боту (`STARS_EFFECTIVE_RUB_PER_STAR` в [`src/services/payment_service.py`](../src/services/payment_service.py)).

**Условие равной маржи (после платёжных издержек, до постоянных расходов):**

`Маржа = Чистая_выручка − 0,6 × минуты`

- YooKassa: `Чистая_выручка = P × 0,897`
- Stars: `Чистая_выручка = S × 1,638` (S — число Stars в инвойсе)

Число Stars: сначала `round(P × 0,897 / 1,638)`, затем **округление до ближайшего кратного 5** (не меньше 5 ⭐) — см. `rub_price_to_stars` в коде.

### Сетка тарифов

| Пакет | Минут | Цена ₽ (YooKassa) | ⭐ (инвойс, кратно 5) | API, ₽ | Маржа после API* (₽, ориентир) |
|-------|-------|-------------------|----------------------|--------|--------------------------------|
| S     | 10    | 59                | 30                   | 6,0    | ≈43,1 (⭐-ветка) |
| M     | 30    | 159               | 85                   | 18,0   | ≈121,2 |
| L     | 60    | 249               | 135                  | 36,0   | ≈185,1 |
| XL    | 300   | 990               | 540                  | 180,0  | ≈704,5 |
| XXL   | 600   | 1850              | 1015                 | 360,0  | ≈1302,6 |

\* Для ₽: `P×0,897 − API`; для ⭐: `S×1,638 − API`. Кратность 5 ⭐ слегка сдвигает маржу относительно «идеальной» ₽-сетки.

**Свой тариф (кастомные минуты):** цена ₽ = `int(мин × 2,5 + 20)`; Stars = `rub_price_to_stars(цена)` (та же функция, что для фиксированных пакетов).

### Куда деваются Stars (кратко)

Пользователь покупает ⭐ в Telegram; бот получает ⭐ на баланс бота. Вывод — через официальный поток (Fragment → TON и далее по вашей схеме). Точные лимиты, холд и курс — только из актуального UI Telegram/Fragment.

### Документация Telegram (не копировать в репозиторий)

- [Bot API — Payments](https://core.telegram.org/bots/payments) (Stars, валюта XTR).
- Актуальные сведения по Stars / выводу — разделы справки Telegram и Fragment.

---

## Рассылка пользователям

Команды доступны только если в `.env` задан **`ADMIN_ID`** (Telegram user id администратора).

**Обязательный тестовый получатель:** `280186359` — на этот аккаунт **всегда** сначала отправляйте тестовое сообщение командой `/broadcast_test`, даже если ваш `ADMIN_ID` другой. Это отдельный «канареечный» пользователь для проверки текста до массовой рассылки.

| Команда | Действие |
|---------|----------|
| `/broadcast_test` | Отправляет заранее заданный текст объявления пользователю `280186359` (см. `BROADCAST_ANNOUNCEMENT_TEXT` в [`src/bot.py`](../src/bot.py)). |
| Скрипт | [`scripts/send_test_announcement.py`](../scripts/send_test_announcement.py) — то же сообщение **только** на `280186359` без массовой рассылки; можно вызвать с сервера, если бот не отвечает (см. [`DEPLOY.md`](DEPLOY.md)). |
| `/broadcast` | Бот просит следующим сообщением прислать текст рассылки; затем рассылает **всем** `users.id` из БД. Между отправками пауза ~50 ms (лимиты Telegram). |
| `/cancel_broadcast` | Отмена режима ожидания текста (после `/broadcast`). |

После деплоя на прод: сначала `/broadcast_test`, проверить у пользователя `280186359`, затем `/broadcast` и текст.

Ошибки доставки (бот заблокирован и т.п.) логируются; рассылка не падает целиком.

---

## Telegram Stars: начисление минут

**Payload инвойса:** `buy_{минуты}_{цена_₽}` — парсится в [`parse_stars_invoice_payload`](../src/services/stars_invoice.py) через `split("_", 2)`.

**Исправление 2026-04 (кастомный тариф):** после ввода минут в «Свой тариф» FSM оставался в `waiting_for_custom_minutes` и перехватывал служебное сообщение об оплате раньше, чем `successful_payment`. В результате Stars списывались, а минуты не начислялись. Сейчас: ввод минут только при `F.text`, после показа кнопок оплаты вызывается `state.set_state(None)` (данные `minutes`/`amount` сохраняются для инвойса). После успешной оплаты — `get_or_create_user` перед транзакцией и `state.clear()` в обработчике.

**Если оплата прошла, а баланс не изменился:** проверьте логи на `Stars payment`. Ручное начисление:

- Команда (только `ADMIN_ID`): `/admin_add_balance <telegram_user_id> <секунды>` (5 мин = `300`).
- SQL (если удобнее на сервере): `UPDATE users SET balance_seconds = balance_seconds + 300 WHERE id = <telegram_user_id>;`

### Миграция БД (FIFO и refund)

Для существующей PostgreSQL один раз выполните [`scripts/migrations/001_stars_refund_fifo.sql`](../scripts/migrations/001_stars_refund_fifo.sql) **до** перезапуска бота с новым кодом.

Автоматический backfill `seconds_remaining = seconds_added` для старых строк **может быть неточным**, если часть купленного баланса уже была израсходована. В сомнительных случаях не включайте закомментированный `UPDATE` в SQL; новые покупки после деплоя получат корректный учёт.

---

## Возврат Telegram Stars (`refundStarPayment`)

Telegram позволяет боту вернуть **целиком** оплату в Stars по идентификатору платежа ([`refundStarPayment`](https://core.telegram.org/bots/api#refundstarpayment)). Частичный refund в Stars **не поддерживается** — возвращать можно только пользователям, которые **не потратили купленные секунды по этой покупке** (в коде: `seconds_remaining >= seconds_added` для строки `transactions`).

**Идентификатор платежа:** `SuccessfulPayment.telegram_payment_charge_id` — сохраняется в `transactions.payment_id`; тот же id используется в `getStarTransactions` для сверки.

**Поток в приложении:**

1. При успешной оплате Stars создаётся строка `transactions` с `provider = telegram_stars`, `invoice_payload`, после `complete_transaction` выставляется `seconds_remaining = seconds_added`.
2. При расходе минут на расшифровку списание с купленного баланса идёт **FIFO** по успешным покупкам (поле `seconds_remaining`), см. [`src/services/db_service.py`](../src/services/db_service.py) и [`src/services/purchased_fifo.py`](../src/services/purchased_fifo.py).
3. Возврат: вызов `await bot.refund_star_payment(user_id=..., telegram_payment_charge_id=...)` ([`stars_refund_service.py`](../src/services/stars_refund_service.py)), затем в БД: уменьшение `users.balance_seconds` на остаток пакета, `seconds_remaining = 0`, `stars_refund_status = refunded`.
4. Повторный возврат того же платежа в Telegram даёт ошибку (например `CHARGE_ALREADY_REFUNDED`); обработчик трактует это как успех и синхронизирует БД, если ещё не помечено.

**Команды (только `ADMIN_ID`):**

| Команда | Действие |
|---------|----------|
| `/admin_refund_stars <transaction_id>` | Полный refund по внутреннему id строки в `transactions`. |
| `/admin_refund_stars_charge <telegram_user_id> <telegram_payment_charge_id>` | То же по id из чека Telegram, если известны пользователь и charge id. |

Ручное начисление без Stars: `/admin_add_balance` создаёт ещё и строку с `provider = manual` для FIFO; **возврат Stars** относится только к `telegram_stars`.

---

## Бесплатный лимит

До **5 минут** аудио суммарно **на аккаунт** (один раз на пробу), без ежедневного сброса — см. логику в [`src/services/db_service.py`](../src/services/db_service.py) (`used_free_seconds`, лимит 300 сек).
