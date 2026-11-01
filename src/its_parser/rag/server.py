from __future__ import annotations

import argparse
import os
import re
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from dotenv import load_dotenv
from loguru import logger
from qdrant_client import QdrantClient

from its_parser.logging_setup import setup_logging
from its_parser.rag.config import Settings
from its_parser.rag.extract import extract_page, load_page_info
from its_parser.rag.indexer import find_pages
from its_parser.rag.search import search
from its_parser.rag.store import COLLECTION_PREFIX, Embedder, QdrantLockedError, list_collections, make_client

_DB_RE = re.compile(r"[A-Za-z0-9_-]+")
_PAGE_RE = re.compile(r"page_\d{4,8}")
MAX_LIMIT = 20
DEFAULT_PAGE_CHARS = 20000

INSTRUCTIONS = (
    "Поиск по документации 1С:Предприятие / 1C:EDT с портала ИТС (its.1c.ru). "
    "Начни с search_docs: он возвращает релевантные фрагменты со ссылкой на ИТС, "
    "page_id и названием базы (db). Полный текст страницы — get_page(db, page_id), "
    "оглавление — list_sections, доступные базы — list_databases."
)


def _check_db(db: str) -> str:
    if not isinstance(db, str) or not _DB_RE.fullmatch(db):
        raise ToolError(f"Недопустимое имя базы: {db!r}")
    return db


def _require_db(settings: Settings, db: str) -> Path:
    """Проверяет имя базы и наличие в ней страниц; возвращает out/<db>."""
    _check_db(db)
    db_dir = settings.db_dir(db)
    if not db_dir.is_dir() or not find_pages(db_dir):
        raise ToolError(f"База '{db}' не найдена в {settings.out_dir}")
    return db_dir


def _page_dir(settings: Settings, db: str, page_id: str) -> Path:
    """out/<db>/<page_id> с защитой от path traversal"""
    root = _require_db(settings, db).resolve()
    if not isinstance(page_id, str) or not _PAGE_RE.fullmatch(page_id):
        raise ToolError(f"Недопустимый page_id: {page_id!r} (ожидается вид page_0001)")
    path = (root / page_id).resolve()
    if path.parent != root:
        raise ToolError(f"Недопустимый page_id: {page_id!r}")
    if not (path / "page.html").is_file():
        raise ToolError(f"Страница {page_id} базы '{db}' не найдена")
    return path


def _fragment(text: str) -> str:
    # первая строка «Раздел: ...» уже отдана отдельными полями
    head, sep, rest = text.partition("\n\n")
    return rest if sep and head.startswith("Раздел: ") else text


def _cite(title: str, number: str, url: str) -> str:
    number = number.rstrip(".")  # в оглавлении номера идут с точкой: «1.1.1.1.»
    return f"{title} ({number}) — {url}" if number else f"{title} — {url}"


def _truncate(text: str, max_chars: int) -> str:
    """Обрезает по границе абзаца (если она не слишком далеко), иначе по границе слова"""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for sep in ("\n\n", "\n", " "):
        pos = cut.rfind(sep)
        if pos >= max_chars * 0.7:
            return cut[:pos].rstrip()
    return cut


class _Backend:
    """Клиент Qdrant и модели эмбеддингов создаются при первом обращении и один раз"""

    def __init__(self, settings: Settings, client: Optional[QdrantClient], embedder: Optional[Embedder]) -> None:
        self.settings = settings
        self._client = client
        self._embedder = embedder
        self._lock = threading.RLock()  # локальный Qdrant и ONNX-сессии — не для параллельных вызовов

    @property
    def client(self) -> QdrantClient:
        with self._lock:
            if self._client is None:
                try:
                    self._client = make_client(self.settings)
                except QdrantLockedError as e:
                    raise ToolError(str(e))
            return self._client

    @property
    def embedder(self) -> Embedder:
        with self._lock:
            if self._embedder is None:
                from its_parser.rag.store import FastEmbedder

                logger.info("Загрузка моделей эмбеддингов: {m}", m=self.settings.dense_model)
                self._embedder = FastEmbedder(self.settings)
            return self._embedder


def create_server(
    settings: Optional[Settings] = None,
    client: Optional[QdrantClient] = None,
    embedder: Optional[Embedder] = None,
) -> FastMCP:
    settings = settings or Settings.from_env()
    backend = _Backend(settings, client, embedder)
    mcp = FastMCP("its-docs", instructions=INSTRUCTIONS)

    @mcp.tool
    def search_docs(query: str, db: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
        """Семантический + полнотекстовый поиск по документации ИТС (1С:Предприятие, 1C:EDT).

        Используй для любых вопросов по документации 1С: сформулируй запрос естественным
        языком или словами из предметной области (названия объектов, команд, настроек).

        Аргументы:
            query: поисковый запрос на русском или английском.
            db: имя базы ИТС (например, "edtdoc"); без значения поиск идёт по всем базам.
                Список баз — list_databases().
            limit: максимум результатов (1–20, по умолчанию 8). Каждая страница
                встречается в выдаче не более одного раза (лучший фрагмент).

        Возвращает список фрагментов по убыванию релевантности. Поля: title (заголовок
        страницы), breadcrumbs (путь по оглавлению), number (номер в оглавлении),
        heading (раздел внутри страницы), fragment (текст фрагмента), url (ссылка на
        страницу в ИТС), cite (готовая строка для цитирования «Заголовок (номер) — url»),
        page_id и db (для get_page), score. score — ранг слияния RRF: служит только для
        сортировки внутри одной выдачи, не нормирован и не является вероятностью;
        сравнивать score разных запросов нельзя.
        """
        if not query or not query.strip():
            raise ToolError("Пустой поисковый запрос")
        if db is not None:
            # пустая строка из UI означает «все базы», а не ошибку имени
            db = db.strip() if isinstance(db, str) else db
            if db:
                _check_db(db)
            else:
                db = None
        limit = max(1, min(int(limit), MAX_LIMIT))
        try:
            with backend._lock:
                hits = search(backend.client, backend.embedder, settings, query.strip(), db=db, limit=limit)
        except ValueError as e:
            raise ToolError(str(e))
        return [
            {
                "title": h.title,
                "breadcrumbs": h.breadcrumbs,
                "number": h.number,
                "heading": h.heading,
                "fragment": _fragment(h.text),
                "url": h.url,
                "cite": _cite(h.title, h.number, h.url),
                "page_id": h.page_id,
                "db": h.db,
                "score": round(h.score, 4),
            }
            for h in hits
        ]

    @mcp.tool
    def get_page(db: str, page_id: str, max_chars: int = DEFAULT_PAGE_CHARS) -> Dict[str, Any]:
        """Возвращает полный текст страницы документации в формате markdown.

        Используй после search_docs, когда фрагмента недостаточно: передай db и page_id
        из результата поиска или из list_sections. Таблицы и блоки кода сохранены,
        картинки даны относительными ссылками (сами файлы не передаются).

        Аргументы:
            db: имя базы ИТС, например "edtdoc".
            page_id: идентификатор страницы вида "page_0042".
            max_chars: максимум символов markdown в ответе (по умолчанию 20000, можно
                от 500 до 200000). Длинная страница обрезается по границе абзаца.

        Возвращает: db, page_id, title, number, breadcrumbs, url (страница в ИТС), markdown,
        truncated (true, если текст обрезан), total_chars (длина полного текста).
        Если truncated, нужный раздел можно найти через search_docs или открыть по url.
        """
        path = _page_dir(settings, db, page_id)
        info = load_page_info(path)
        max_chars = max(500, min(int(max_chars), 200000))
        markdown = extract_page(path)
        return {
            "db": db,
            "page_id": page_id,
            "title": info.title,
            "number": info.number,
            "breadcrumbs": info.breadcrumbs,
            "url": info.url,
            "markdown": _truncate(markdown, max_chars),
            "truncated": len(markdown) > max_chars,
            "total_chars": len(markdown),
        }

    @mcp.tool
    def list_sections(db: str, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """Оглавление базы ИТС: список страниц с номерами, заголовками и ссылками.

        Помогает ориентироваться в структуре документации и находить соседние страницы.
        Для больших баз задавай prefix, чтобы не получать всё оглавление сразу.

        Аргументы:
            db: имя базы ИТС, например "edtdoc".
            prefix: необязательный номер раздела в оглавлении, например "1.2" — вернутся
                страницы раздела 1.2 и всех его подразделов (1.2.1, 1.2.2.1 и т.д., но не 1.20).
                Без prefix возвращается всё оглавление.

        Возвращает список в порядке оглавления: number, title, level (глубина, с 0),
        page_id (для get_page), url.
        """
        pages = find_pages(_require_db(settings, db))
        norm = None
        if prefix:
            norm = prefix.strip().rstrip(".") + "."
        result = []
        for page_dir in pages:
            info = load_page_info(page_dir)
            if norm is not None and not info.number.startswith(norm):
                continue
            result.append({
                "number": info.number,
                "title": info.title,
                "level": info.level,
                "page_id": info.page_id,
                "url": info.url,
            })
        return result

    @mcp.tool
    def list_databases() -> List[Dict[str, Any]]:
        """Список проиндексированных баз документации ИТС.

        Вызывай, чтобы узнать, какие значения db доступны для search_docs, get_page
        и list_sections. Возвращает по каждой базе: db, pages (число страниц) и
        chunks (число фрагментов в поисковом индексе).
        """
        with backend._lock:
            client = backend.client
            databases = []
            for name in list_collections(client):
                page_ids = set()
                offset = None
                while True:
                    points, offset = client.scroll(
                        name, limit=1000, offset=offset, with_vectors=False, with_payload=["page_id"],
                    )
                    page_ids.update(p.payload["page_id"] for p in points if p.payload)
                    if offset is None:
                        break
                databases.append({
                    "db": name[len(COLLECTION_PREFIX):],
                    "pages": len(page_ids),
                    "chunks": client.count(name, exact=True).count,
                })
        return databases

    return mcp


def serve(settings: Settings, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8080) -> None:
    """Запускает MCP-сервер. stdio: stdout занят протоколом, логи идут только в stderr"""
    mcp = create_server(settings)
    if transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
    elif transport == "http":
        logger.info("MCP-сервер: http://{h}:{p}/mcp", h=host, p=port)
        mcp.run(transport="http", host=host, port=port, show_banner=False)
    else:
        raise ValueError(f"Неизвестный транспорт: {transport}")


def mcp_main(argv: Optional[List[str]] = None) -> None:
    load_dotenv()  # ITS_* из .env, если он есть
    parser = argparse.ArgumentParser(description="MCP-сервер поиска по документации ИТС")
    parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio',
                        help='stdio — для Claude Code, http — streamable-http (по умолчанию: stdio)')
    parser.add_argument('--host', default=os.environ.get('ITS_MCP_HOST', '127.0.0.1'),
                        help='Адрес для http (по умолчанию 127.0.0.1; в Docker — 0.0.0.0)')
    parser.add_argument('--port', type=int, default=int(os.environ.get('ITS_MCP_PORT', '8080')),
                        help='Порт для http (по умолчанию 8080)')
    parser.add_argument('--out-dir', help='Каталог с загруженными базами (по умолчанию ITS_OUT_DIR или out)')
    parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = parser.parse_args(argv)

    setup_logging(stdout_level=args.log_level)  # sink — stderr, stdout не трогаем
    settings = Settings.from_env()
    if args.out_dir:
        settings = replace(settings, out_dir=Path(args.out_dir))
    serve(settings, args.transport, args.host, args.port)
