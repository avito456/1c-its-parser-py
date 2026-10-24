from __future__ import annotations

import argparse
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from loguru import logger

from its_parser.logging_setup import setup_logging
from its_parser.rag.config import Settings
from its_parser.rag.indexer import find_pages, index_db
from its_parser.rag.store import QdrantLockedError

_DB_RE = re.compile(r'[A-Za-z0-9_-]+')


def discover_dbs(out_dir: Path) -> List[str]:
    """Базы в out_dir: подкаталоги с page_*/page.html"""
    if not Path(out_dir).is_dir():
        return []
    return sorted(
        d.name for d in Path(out_dir).iterdir()
        if d.is_dir() and _DB_RE.fullmatch(d.name) and find_pages(d)
    )


def find_orphans(client, settings: Settings) -> List[str]:
    """Имена баз, у которых есть коллекция its_<db>, но нет каталога out/<db> со страницами"""
    from its_parser.rag.store import COLLECTION_PREFIX, list_collections

    on_disk = set(discover_dbs(settings.out_dir))
    names = (c[len(COLLECTION_PREFIX):] for c in list_collections(client))
    return [db for db in names if db not in on_disk]


def run_index(dbs: List[str], settings: Settings, reindex: bool = False,
              prune: bool = False, warn_orphans: bool = False) -> None:
    """Индексирует перечисленные базы (эмбеддер и клиент создаются один раз).

    prune удаляет осиротевшие коллекции, warn_orphans только предупреждает о них.
    Клиент Qdrant закрывается на выходе: локальное хранилище открывает один процесс."""
    from its_parser.rag.store import FastEmbedder, make_client

    for db in dbs:
        if not _DB_RE.fullmatch(db):
            raise ValueError(f"Недопустимое имя базы: {db}")
    client = make_client(settings)
    try:
        if dbs:
            embedder = FastEmbedder(settings)
            for db in dbs:
                index_db(db, settings, client, embedder, reindex=reindex)
        orphans = find_orphans(client, settings) if (prune or warn_orphans) else []
        for db in orphans:
            if prune:
                client.delete_collection(settings.collection_name(db))
                logger.info("Удалена коллекция {c}: нет каталога {d}", c=settings.collection_name(db), d=settings.db_dir(db))
            else:
                logger.warning("Коллекция {c} осиротела: нет каталога {d} (its-index --prune удалит её)",
                               c=settings.collection_name(db), d=settings.db_dir(db))
    finally:
        client.close()


def index_main(argv: Optional[List[str]] = None) -> None:
    load_dotenv()  # ITS_* из .env, если он есть
    parser = argparse.ArgumentParser(
        description="Индексация скачанной документации ИТС (out/<db>) в Qdrant для RAG/MCP",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--db', help='Имя базы ИТС (каталог out/<db>), например edtdoc')
    group.add_argument('--all', action='store_true', help='Проиндексировать все базы из каталога вывода')
    parser.add_argument('--out-dir', help='Каталог с загруженными базами (по умолчанию ITS_OUT_DIR или out)')
    parser.add_argument('--prune', action='store_true',
                        help='Удалить коллекции its_*, для которых нет каталога out/<db> (можно без --db/--all)')
    parser.add_argument('--reindex', action='store_true', help='Пересоздать коллекцию с нуля')
    parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = parser.parse_args(argv)

    setup_logging(stdout_level=args.log_level)
    settings = Settings.from_env()
    if args.out_dir:
        settings = replace(settings, out_dir=Path(args.out_dir))

    if not (args.db or args.all or args.prune):
        parser.error("укажите --db NAME, --all или --prune")

    if args.all:
        dbs = discover_dbs(settings.out_dir)
        if not dbs and not args.prune:
            logger.error("В {d} не найдено ни одной загруженной базы", d=settings.out_dir)
            raise SystemExit(1)
    else:
        dbs = [args.db] if args.db else []
        for db in dbs:
            if not _DB_RE.fullmatch(db):
                logger.error("Недопустимое имя базы: {db}", db=db)
                raise SystemExit(1)
            if not find_pages(settings.db_dir(db)):
                logger.error("Нет загруженной базы '{db}': в {d} не найдено страниц (page_*/page.html). "
                             "Сначала скачайте её: its-parser --url .../db/{db} ...",
                             db=db, d=settings.db_dir(db))
                raise SystemExit(1)

    try:
        run_index(dbs, settings, reindex=args.reindex, prune=args.prune, warn_orphans=args.all)
    except QdrantLockedError as e:
        logger.error("{e}", e=e)
        raise SystemExit(1)
