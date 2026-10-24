from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from qdrant_client import QdrantClient, models

from its_parser.rag.config import Settings
from its_parser.rag.store import DENSE, SPARSE, Embedder, list_collections

PREFETCH_LIMIT = 40


@dataclass
class SearchHit:
    score: float
    db: str
    page_id: str
    title: str
    heading: str
    breadcrumbs: List[str] = field(default_factory=list)
    number: str = ""
    url: str = ""
    text: str = ""
    chunk_idx: int = 0


def _hit(point: models.ScoredPoint) -> SearchHit:
    p = point.payload or {}
    return SearchHit(
        score=point.score,
        db=p.get("db", ""),
        page_id=p.get("page_id", ""),
        title=p.get("title", ""),
        heading=p.get("heading", ""),
        breadcrumbs=list(p.get("breadcrumbs", [])),
        number=p.get("number", ""),
        url=p.get("url", ""),
        text=p.get("text", ""),
        chunk_idx=p.get("chunk_idx", 0),
    )


def search(
    client: QdrantClient,
    embedder: Embedder,
    settings: Settings,
    query: str,
    db: Optional[str] = None,
    limit: int = 8,
    dedup: bool = True,
) -> List[SearchHit]:
    """Гибридный поиск (dense + sparse BM25, слияние RRF) по базе db или по всем its_*.
    dedup оставляет лучший фрагмент каждой страницы."""
    if db:
        collections = [settings.collection_name(db)]
        if not client.collection_exists(collections[0]):
            raise ValueError(f"База '{db}' не проиндексирована")
    else:
        collections = list_collections(client)

    dense, sparse = embedder.embed_query(query)
    fetch = limit * 4 if dedup else limit
    hits: List[SearchHit] = []
    for collection in collections:
        response = client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dense, using=DENSE, limit=PREFETCH_LIMIT),
                models.Prefetch(query=sparse, using=SPARSE, limit=PREFETCH_LIMIT),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=fetch,
            with_payload=True,
        )
        hits.extend(_hit(p) for p in response.points)

    hits.sort(key=lambda h: h.score, reverse=True)
    if dedup:
        best: Dict[tuple, SearchHit] = {}
        for h in hits:
            best.setdefault((h.db, h.page_id), h)
        hits = list(best.values())
    return hits[:limit]
