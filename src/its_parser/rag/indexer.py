from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger
from qdrant_client import QdrantClient, models

from its_parser.rag.chunker import CHUNKER_VERSION, Chunk, chunk_markdown
from its_parser.rag.config import Settings
from its_parser.rag.extract import extract_page, load_page_info
from its_parser.rag.store import DENSE, SPARSE, Embedder, ensure_collection

_NAMESPACE = uuid.UUID("6f1b6a0e-3c0b-4d8e-9d0a-1c1c1c1c1c1c")
BATCH_SIZE = 32


@dataclass
class IndexStats:
    pages_total: int = 0
    pages_indexed: int = 0
    pages_skipped: int = 0
    pages_deleted: int = 0
    chunks: int = 0


def chunk_point_id(db: str, page_id: str, chunk_idx: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{db}/{page_id}/{chunk_idx}"))


def find_pages(db_dir: Path) -> List[Path]:
    return sorted(p for p in Path(db_dir).glob("page_*") if (p / "page.html").is_file())


def _page_filter(page_ids: List[str]) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="page_id", match=models.MatchAny(any=page_ids))])


def _indexed_pages(client: QdrantClient, collection: str) -> Dict[str, Tuple[str, int, int]]:
    """page_id → (content_hash, chunk_count из payload, фактическое число чанков в коллекции)"""
    hashes: Dict[str, Tuple[str, int]] = {}
    actual: Counter = Counter()
    offset = None
    while True:
        points, offset = client.scroll(
            collection, limit=1000, offset=offset, with_vectors=False,
            with_payload=["page_id", "content_hash", "chunk_count"],
        )
        for p in points:
            pl = p.payload or {}
            hashes[pl["page_id"]] = (pl.get("content_hash", ""), pl.get("chunk_count", -1))
            actual[pl["page_id"]] += 1
        if offset is None:
            break
    return {pid: (h, n, actual[pid]) for pid, (h, n) in hashes.items()}


def content_hash(markdown: str, info) -> str:
    meta = json.dumps(
        [CHUNKER_VERSION, info.title, info.number, info.url, info.breadcrumbs], ensure_ascii=False,
    )
    return hashlib.sha256(f"{meta}\n{markdown}".encode("utf-8")).hexdigest()


def index_db(
    db: str,
    settings: Settings,
    client: QdrantClient,
    embedder: Embedder,
    reindex: bool = False,
    db_dir: Optional[Path] = None,
    batch_size: int = BATCH_SIZE,
) -> IndexStats:
    """Индексирует out/<db> в коллекцию its_<db>. Неизменённые страницы пропускаются,
    исчезнувшие — удаляются. Страница считается неизменённой, если совпал хэш контента
    и в коллекции полный набор её чанков."""
    db_dir = Path(db_dir or settings.db_dir(db))
    pages = find_pages(db_dir)
    if not pages:
        raise FileNotFoundError(f"В {db_dir} нет страниц (page_*/page.html)")

    collection = settings.collection_name(db)
    if reindex and client.collection_exists(collection):
        logger.info("Удаление коллекции {c} (--reindex)", c=collection)
        client.delete_collection(collection)
    ensure_collection(client, collection, embedder.dense_dim)

    known = _indexed_pages(client, collection)
    stats = IndexStats(pages_total=len(pages))

    current_ids = {p.name for p in pages}
    gone = sorted(set(known) - current_ids)
    if gone:
        client.delete(collection, points_selector=models.FilterSelector(filter=_page_filter(gone)))
        stats.pages_deleted = len(gone)
        logger.info("Удалено страниц, которых больше нет в {d}: {n}", d=db_dir, n=len(gone))

    buffer: List[Tuple[Chunk, str, int]] = []

    def flush() -> None:
        if not buffer:
            return
        dense, sparse = embedder.embed_passages([c.text for c, _, _ in buffer])
        points = []
        for (chunk, chash, count), dv, sv in zip(buffer, dense, sparse):
            payload = chunk.payload()
            payload["content_hash"] = chash
            payload["chunk_count"] = count
            points.append(models.PointStruct(
                id=chunk_point_id(chunk.db, chunk.page_id, chunk.chunk_idx),
                vector={DENSE: dv, SPARSE: sv},
                payload=payload,
            ))
        client.upsert(collection, points=points)
        buffer.clear()

    for i, page_dir in enumerate(pages, 1):
        page_id = page_dir.name
        info = load_page_info(page_dir)
        markdown = extract_page(page_dir)
        chash = content_hash(markdown, info)
        old = known.get(page_id)
        if old and old[0] == chash and old[1] == old[2]:
            stats.pages_skipped += 1
            logger.debug("[{i}/{n}] {p}: не изменилась", i=i, n=len(pages), p=page_id)
            continue

        chunks = chunk_markdown(markdown, info, db)
        if old:
            # старые чанки могут не совпасть по числу с новыми — чистим страницу целиком
            flush()
            client.delete(collection, points_selector=models.FilterSelector(filter=_page_filter([page_id])))
        for chunk in chunks:
            buffer.append((chunk, chash, len(chunks)))
            if len(buffer) >= batch_size:
                flush()
        stats.pages_indexed += 1
        stats.chunks += len(chunks)
        logger.info("[{i}/{n}] {p} «{t}»: {c} чанков", i=i, n=len(pages), p=page_id, t=info.title, c=len(chunks))
    flush()

    logger.info(
        "{db}: страниц {total}, проиндексировано {idx} ({chunks} чанков), без изменений {skip}, удалено {gone}",
        db=db, total=stats.pages_total, idx=stats.pages_indexed, chunks=stats.chunks,
        skip=stats.pages_skipped, gone=stats.pages_deleted,
    )
    return stats
