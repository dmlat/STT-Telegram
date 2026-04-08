# Пример переменных окружения (`.env`)

Скопируйте в `.env` и подставьте значения. **Не коммитьте** `.env` с секретами.

```env
# Обязательно
BOT_TOKEN=

# БД (должны совпадать с сервисом db в docker-compose, если используете его)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
POSTGRES_DB=stt_db
DB_PORT=5434

# URL для приложения внутри Docker (asyncpg)
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@db:5432/stt_db

# OpenAI
OPENAI_KEY=

# Google Sheets (опционально)
GOOGLE_CREDENTIALS_PATH=credentials.json

# YooKassa (если пусто — в боте только бесплатный тариф и Stars)
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=

# Админ: рассылка /broadcast*, /broadcast_test; должен совпадать с вашим Telegram user id
ADMIN_ID=
```

Пояснения:

- **`ADMIN_ID`** — целое число (Telegram user id). Без него команды рассылки недоступны.
- **`DATABASE_URL`** на хосте без Docker может быть другим (например `localhost` и порт `DB_PORT`).
