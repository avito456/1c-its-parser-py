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

_DB_RE = re.compile(r'[A-Za-z0-9_-]+')


def discover_dbs(out_dir: Path) -> List[str]:
    """Базы в out_dir: подкаталоги с page_*/page.html"""
    if not Path(out_dir).is_dir():
        return []
    return sorted(
        d.name for d in Path(out_dir).iterdir()
        if d.is_dir() and _DB_RE.fullmatch(d.name) and find_pages(d)
    )


def run_index(dbs: List[str], settings: Settings, reindex: bool = False) -> None:
    """Индексирует перечисленные базы (эмбеддер и клиент создаются один раз)"""
    from its_parser.rag.store import FastEmbedder, make_client

    for db in dbs:
        if not _DB_RE.fullmatch(db):
            raise ValueError(f"Недопустимое имя базы: {db}")
    client = make_client(settings)
    try:
        embedder = FastEmbedder(settings)
        for db in dbs:
            index_db(db, settings, client, embedder, reindex=reindex)
    finally:
        client.close()


def index_main(argv: Optional[List[str]] = None) -> None:
    load_dotenv()  # ITS_* из .env, если он есть
    parser = argparse.ArgumentParser(
        description="Индексация скачанной документации ИТС (out/<db>) в Qdrant для RAG/MCP",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--db', help='Имя базы ИТС (каталог out/<db>), например edtdoc')
    group.add_argument('--all', action='store_true', help='Проиндексировать все базы из каталога вывода')
    parser.add_argument('--out-dir', help='Каталог с загруженными базами (по умолчанию ITS_OUT_DIR или out)')
    parser.add_argument('--reindex', action='store_true', help='Пересоздать коллекцию с нуля')
    parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = parser.parse_args(argv)

    setup_logging(stdout_level=args.log_level)
    settings = Settings.from_env()
    if args.out_dir:
        settings = replace(settings, out_dir=Path(args.out_dir))

    dbs = discover_dbs(settings.out_dir) if args.all else [args.db]
    if not dbs:
        logger.error("В {d} не найдено ни одной загруженной базы", d=settings.out_dir)
        raise SystemExit(1)
    run_index(dbs, settings, reindex=args.reindex)
