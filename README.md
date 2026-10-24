# Парсер документации 1С ИТС + RAG + MCP

Инструмент скачивает документацию с [сайта ИТС](https://its.1c.ru), строит по ней поисковый
индекс (гибридный поиск: смысловой + BM25) и отдаёт её LLM через MCP-сервер.

```
its-parser --url .../db/edtdoc ... [--index] [--serve]
  crawl  → out/edtdoc/page_XXXX/{page.html, metadata.json, images/}
  index  → html→markdown → чанки по заголовкам → fastembed → Qdrant (коллекция its_edtdoc)
  serve  → MCP: stdio (Claude Code) | streamable-http (Docker, :8080)
```

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Скачивание документации](#скачивание-документации)
- [Индексация и MCP-сервер](#индексация-и-mcp-сервер)
- [Подключение к Claude Code](#подключение-к-claude-code)
- [Docker](#docker)
- [Переменные окружения](#переменные-окружения)
- [Структура данных](#структура-данных)
- [Тесты](#тесты)
- [Устранение неполадок](#устранение-неполадок)

## Возможности

- Авторизация на сайте 1С ИТС, извлечение структуры документации с учётом иерархии разделов
- Сохранение HTML-страниц и изображений, локальное оглавление `index.html`
- Метаданные страниц в `metadata.json`: заголовок, номер, уровень, URL, хлебные крошки
- Индексация в Qdrant: dense-эмбеддинги (fastembed, `intfloat/multilingual-e5-large`) + sparse BM25, слияние RRF
- Инкрементальная переиндексация: неизменённые страницы пропускаются, удалённые убираются из индекса
- MCP-сервер с инструментами `search_docs`, `get_page`, `list_sections`, `list_databases`
- Каждая база ИТС (`/db/<db>`) хранится отдельно: `out/<db>/` и коллекция `its_<db>`

## Установка

Требования: Python 3.10+, [uv](https://docs.astral.sh/uv/). Для скачивания документации
нужны Google Chrome/Chromium и подходящий ChromeDriver (индексация и сервер браузер не используют).

```bash
uv sync --extra rag            # парсер + индексатор + MCP-сервер
uv sync --extra rag --extra dev  # плюс pytest
```

Без `--extra rag` ставится только парсер.

## Быстрый старт

```bash
cp .env.example .env           # впишите USERNAME и PASSWORD от login.1c.ru

# скачать, проиндексировать и запустить MCP-сервер (stdio)
uv run its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login --index --serve
```

Первая индексация скачает модели (около 2 ГБ) в `data/models`.

## Скачивание документации

```bash
uv run its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login
uv run its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login \
    --username <логин> --password <пароль> --limit 50 --headless
```

Учётные данные можно передать аргументами или через `.env` (`USERNAME`, `PASSWORD`) —
второй способ предпочтительнее, чтобы пароль не попадал в историю shell.
Не коммитьте `.env` и не вписывайте реальные логин и пароль в документацию.

Имя базы определяется из URL (`/db/<db>`), страницы сохраняются в `out/<db>/`.
Перед загрузкой очищается только `out/<db>`.

| Параметр | Описание |
|----------|----------|
| `--url` | URL документации, обязателен (`https://its.1c.ru/db/<db>`) |
| `--login` | URL страницы входа (нужен, если не указан `--no-crawl`) |
| `--username`, `--password` | Учётные данные (иначе из `.env`) |
| `--limit N` | Загрузить только первые N страниц |
| `--headless` | Браузер без окна |
| `--out-dir DIR` | Корневой каталог вывода (по умолчанию `out`) |
| `--no-crawl` | Не скачивать; только `--index`/`--serve` для готового `out/<db>` |
| `--index` | Проиндексировать `out/<db>` после загрузки |
| `--serve` | Запустить MCP-сервер после загрузки/индексации |
| `--transport stdio\|http` | Транспорт для `--serve` (по умолчанию `stdio`) |
| `--host`, `--port` | Адрес и порт для `--transport http` (по умолчанию `127.0.0.1:8080`) |
| `--log-level`, `--log-file`, `--log-file-level` | Логирование |

## Индексация и MCP-сервер

```bash
uv run its-index --db edtdoc            # одна база (out/edtdoc)
uv run its-index --all                  # все базы из out/
uv run its-index --db edtdoc --reindex  # пересоздать коллекцию с нуля

uv run its-mcp                          # stdio (для Claude Code)
uv run its-mcp --transport http --port 8080   # streamable-http: http://127.0.0.1:8080/mcp
```

Повторный `its-index` пропускает неизменённые страницы. После смены модели
(`ITS_DENSE_MODEL`) нужен `--reindex`. В stdio-режиме stdout занят протоколом MCP,
все логи идут в stderr.

### Инструменты MCP

| Инструмент | Назначение |
|------------|------------|
| `search_docs(query, db=None, limit=8)` | Поиск: заголовок, хлебные крошки, ссылка на ИТС, `page_id`, `db`, фрагмент |
| `get_page(db, page_id)` | Полный markdown страницы |
| `list_sections(db, prefix=None)` | Оглавление базы; `prefix` — номер раздела (`1.2`) |
| `list_databases()` | Проиндексированные базы и число страниц/чанков |

### Локальный Qdrant и блокировка

По умолчанию индекс лежит в `data/qdrant` (локальный режим Qdrant). Такой каталог может
открывать **только один процесс**: пока работает `its-mcp`, запустить `its-index` не выйдет
(и наоборот). Варианты: остановить сервер на время индексации, использовать
`its-parser --index --serve` (индексатор закрывается до старта сервера) либо вынести
Qdrant в отдельный сервер и задать `ITS_QDRANT_URL` — так работает [Docker](#docker).

## Подключение к Claude Code

stdio (сервер запускается самим Claude Code):

```bash
claude mcp add its-docs -- uv run --directory /путь/к/1c-its-parser-py its-mcp
```

HTTP (сервер запущен отдельно, например в Docker):

```bash
claude mcp add --transport http its-docs http://localhost:8080/mcp
```

У MCP-сервера нет аутентификации, поэтому по умолчанию он слушает только localhost.

## Docker

Краулер (Selenium/Chrome) в контейнере не работает: документацию скачайте на хосте,
в контейнер она монтируется только для чтения.

```bash
uv run its-parser --url https://its.1c.ru/db/edtdoc --login https://login.1c.ru/login  # → out/edtdoc
docker compose up -d --build
docker compose ps          # its-mcp станет healthy после индексации
claude mcp add --transport http its-docs http://localhost:8080/mcp
docker compose down        # без -v: индекс и модели сохраняются на хосте
```

Состав `docker-compose.yml`:

- `qdrant` (`qdrant/qdrant:v1.20.0`, версия совпадает с `qdrant-client`) — отдельный сервер, данные в `./data/qdrant-server`
- `its-mcp` — образ на `python:3.12-slim` (multi-stage, пользователь без прав root, зависимости из `uv.lock`, только extra `rag`);
  выполняет `its-index --all && its-mcp --transport http --host 0.0.0.0 --port 8080`;
  тома `./out:/data/out:ro` и `./data/models:/data/models` (кэш моделей — не скачиваются при каждом старте);
  порт публикуется на `127.0.0.1:8080`

Чтобы открыть порт в сеть, замените `127.0.0.1:8080:8080` на `8080:8080` и позаботьтесь о защите.
Новые страницы подхватываются перезапуском: `docker compose restart its-mcp`.

## Переменные окружения

Читаются из окружения и `.env` (шаблон — `.env.example`).

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `USERNAME`, `PASSWORD` | — | Учётная запись login.1c.ru (только для скачивания) |
| `LOG_LEVEL`, `LOG_FILE`, `LOG_FILE_LEVEL` | `INFO`, —, `DEBUG` | Логирование |
| `ITS_OUT_DIR` | `out` | Каталог со скачанными базами |
| `ITS_DATA_DIR` | `data` | Корень данных (Qdrant, кэш моделей) |
| `ITS_QDRANT_PATH` | `<ITS_DATA_DIR>/qdrant` | Локальное хранилище Qdrant |
| `ITS_QDRANT_URL` | — | Адрес внешнего Qdrant; если задан, локальное хранилище не используется |
| `ITS_DENSE_MODEL` | `intfloat/multilingual-e5-large` | Dense-модель fastembed (префиксы `query:`/`passage:` для e5 ставятся автоматически) |
| `ITS_SPARSE_MODEL` | `Qdrant/bm25` | Sparse-модель |
| `ITS_MODELS_CACHE` | `<ITS_DATA_DIR>/models` | Кэш моделей |
| `ITS_MCP_HOST`, `ITS_MCP_PORT` | `127.0.0.1`, `8080` | Адрес `its-mcp --transport http` |

## Структура данных

```
out/<db>/
  index.html            оглавление со ссылками на сохранённые страницы
  page_XXXX/
    page.html           содержимое страницы
    metadata.json       title, level, number, url, breadcrumbs
    metadata.txt        то же в текстовом виде (title, level, url)
    images/             изображения страницы
data/
  qdrant/               локальный индекс (без ITS_QDRANT_URL)
  qdrant-server/        данные Qdrant из docker compose
  models/               кэш моделей fastembed
```

## Тесты

```bash
uv sync --extra rag --extra dev
uv run pytest                   # быстрые тесты (фейковый эмбеддер, Qdrant в памяти)
uv run pytest -m slow           # с реальными моделями (скачивают модели)
```

## Устранение неполадок

1. **Ошибки авторизации** — проверьте учётные данные и URL входа (`--login`).
2. **Таймауты при загрузке** — для больших баз нужно время; ограничьте объём через `--limit`.
3. **`Storage folder ... is already accessed by another instance`** — локальный Qdrant открыт
   другим процессом (`its-mcp`, `its-index`). Остановите его или используйте `ITS_QDRANT_URL` / `docker compose`.
4. **`its-mcp` отвечает «База не проиндексирована»** — выполните `its-index --db <db>`.
5. **Контейнер `its-mcp` перезапускается** — проверьте `docker compose logs its-mcp`: чаще всего в `./out`
   нет скачанных баз (`its-index --all` завершается ошибкой).
6. **Изображения не отображаются в документации ERP** — парсер учитывает специфику путей ERP; если проблема
   осталась, запустите без `--headless`, проверьте папку `images` страницы и консоль браузера (F12).
