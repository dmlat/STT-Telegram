# Деплой

## Бот и БД (Docker)

1. На сервере: клонировать репозиторий, создать `.env` по образцу [`ENV_EXAMPLE.md`](ENV_EXAMPLE.md).
2. Положить `credentials.json` для Google Sheets (если используется), путь задать в `GOOGLE_CREDENTIALS_PATH` в compose или `.env`.
3. Запуск: `docker compose up --build -d` из корня проекта (см. [`docker-compose.yml`](../docker-compose.yml)).
4. Обновление: скрипт [`update.sh`](../update.sh) — `git pull`, затем `docker compose up --build -d`.

Сервисы: `bot` (код из тома `.:/app`), `db` (PostgreSQL 15). Порт БД наружу: `DB_PORT` из `.env` (по умолчанию 5434).

## Лендинг (GitHub Pages)

Сайт **не** собирается из каталога `/landing` в настройках GitHub Pages напрямую: публикуется ветка **`gh-pages`**, **корень ветки** = корень сайта (`index.html`, `privacy.html`, `CNAME`, …).

Исходники на **`main`** лежат в папке [`landing/`](../landing/). После правок:

1. Закоммитить изменения в `landing/` на `main`.
2. Перенести изменённые файлы в корень ветки `gh-pages` (тот же `index.html`, `privacy.html`, `style.css` и т.д.) и закоммитить `gh-pages`.
3. Не удалять на `gh-pages` бинарники, которых нет в `landing/` (`favicon.png`, `screenshot.webp`), если не добавили их в `landing/`.

Кастомный домен: файл `CNAME` с именем хоста (например `golosvtekst.ru`) в корне `gh-pages`.

После пуша подождать обновления CDN (минуты).

## Порядок после релиза с рассылкой

1. Задеплоить бота (`update.sh` или ручной `docker compose`).
2. В Telegram от имени админа: `/broadcast_test` → проверить у пользователя `280186359`.
3. `/broadcast` и текст объявления.
