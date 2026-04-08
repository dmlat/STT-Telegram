# STT — Telegram-бот «Голос в текст»

Репозиторий содержит код Telegram-бота для расшифровки аудио и статический лендинг сервиса.

## Операторская документация

- [ReadMe/PROD.md](ReadMe/PROD.md) — тарифы, Stars, маржа, рассылка
- [ReadMe/DEPLOY.md](ReadMe/DEPLOY.md) — Docker, обновление бота, деплой лендинга на GitHub Pages
- [ReadMe/ENV_EXAMPLE.md](ReadMe/ENV_EXAMPLE.md) — пример `.env`

## Лендинг и GitHub Pages

- **Публичный сайт:** [https://golosvtekst.ru/](https://golosvtekst.ru/)
- **Хостинг:** [GitHub Pages](https://pages.github.com/), публикуется из ветки **`gh-pages`** (корень ветки = корень сайта).
- **Кастомный домен:** в корне `gh-pages` лежит файл `CNAME` со значением `golosvtekst.ru` (в репозитории дубликат также есть в [`landing/CNAME`](landing/CNAME) и в корне [`CNAME`](CNAME) на `main` для удобства).

### Синхронизация `main` и `gh-pages`

Исходники страниц на ветке **`main`** лежат в папке [`landing/`](landing/). Ветка **`gh-pages`** должна содержать те же HTML/CSS и связанные файлы **в корне** (например `index.html`, `privacy.html`, `style.css`), иначе сайт не обновится.

При правках лендинга: измените файлы в `landing/`, закоммитьте на `main`, затем перенесите нужные файлы в корень `gh-pages` и закоммитьте туда (сейчас деплой не автоматизирован — нет workflow в `.github/workflows`).

### Статические файлы только на `gh-pages`

В `landing/` могут отсутствовать бинарные файлы, которые уже есть в корне **`gh-pages`** и на которые ссылается HTML (например `favicon.png`, `screenshot.webp`). Не удаляйте их при обновлении сайта с `landing/`, если не добавили копии в `landing/`.

## Яндекс.Вебмастер

Подтверждение прав на сайт — мета-тег в `<head>` главной страницы:

```html
<meta name="yandex-verification" content="12deb01d7ea92044" />
```

После успешной проверки тег **не удалять** (рекомендация Яндекса).

## Яндекс.Метрика

На всех страницах лендинга в `<head>` подключён счётчик **108441396** (вебвизор, карта кликов, `dataLayer` для электронной коммерции). При добавлении новых HTML-страниц вставляйте тот же фрагмент из [`landing/index.html`](landing/index.html) сразу после `viewport`.

## Google Search Console

Подтверждение через HTML-файл: в корне сайта (и в [`landing/`](landing/) на `main`) должен лежать [`google9be8855c40e4f8d7.html`](landing/google9be8855c40e4f8d7.html), доступный по адресу `https://golosvtekst.ru/google9be8855c40e4f8d7.html`. Файл **не удалять** после успешной проверки.

## Бот (локально)

См. [`docker-compose.yml`](docker-compose.yml): сервис `bot` и PostgreSQL. Переменные окружения — в `.env` (шаблон не коммитится).
