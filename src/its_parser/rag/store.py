from __future__ import annotations

import warnings
from typing import List, Protocol, Sequence, Tuple

from qdrant_client import QdrantClient, models

from its_parser.rag.config import Settings

DENSE = "dense"
SPARSE = "sparse"
COLLECTION_PREFIX = "its_"


class Embedder(Protocol):
    """Эмбеддер документов и запросов: dense + sparse"""

    dense_dim: int

    def embed_passages(self, texts: Sequence[str]) -> Tuple[List[List[float]], List[models.SparseVector]]: ...

    def embed_query(self, query: str) -> Tuple[List[float], models.SparseVector]: ...


class FastEmbedder:
    """dense и sparse модели fastembed; префиксы e5 (query:/passage:) добавляются здесь,
    потому что passage_embed/query_embed в fastembed префиксов не ставят"""

    def __init__(self, settings: Settings, batch_size: int = 16) -> None:
        from fastembed import SparseTextEmbedding, TextEmbedding

        cache = str(settings.models_cache) if settings.models_cache else None
        self._settings = settings
        self._batch_size = batch_size
        self.dense_dim = TextEmbedding.get_embedding_size(settings.dense_model)
        self._dense = TextEmbedding(settings.dense_model, cache_dir=cache)
        self._sparse = SparseTextEmbedding(settings.sparse_model, cache_dir=cache)

    @staticmethod
    def _sv(emb) -> models.SparseVector:
        return models.SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())

    def embed_passages(self, texts):
        prefix = self._settings.passage_prefix
        dense = self._dense.passage_embed([prefix + t for t in texts], batch_size=self._batch_size)
        sparse = self._sparse.passage_embed(list(texts), batch_size=self._batch_size)
        return [v.tolist() for v in dense], [self._sv(s) for s in sparse]

    def embed_query(self, query):
        dense = next(iter(self._dense.query_embed(self._settings.query_prefix + query)))
        sparse = next(iter(self._sparse.query_embed(query)))
        return dense.tolist(), self._sv(sparse)


def make_client(settings: Settings) -> QdrantClient:
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url)
    path = str(settings.qdrant_path)
    if path != ":memory:":
        settings.qdrant_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=path)


def ensure_collection(client: QdrantClient, name: str, dense_dim: int) -> None:
    if client.collection_exists(name):
        params = client.get_collection(name).config.params.vectors
        size = params[DENSE].size if isinstance(params, dict) and DENSE in params else None
        if size != dense_dim:
            raise RuntimeError(
                f"Коллекция {name} создана с другой моделью (размерность {size}, нужна {dense_dim}); "
                f"запустите переиндексацию с --reindex"
            )
        return
    client.create_collection(
        collection_name=name,
        vectors_config={DENSE: models.VectorParams(size=dense_dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    with warnings.catch_warnings():
        # в локальном режиме индексы не действуют, на сервере ускоряют фильтр по page_id
        warnings.simplefilter("ignore", UserWarning)
        client.create_payload_index(name, "page_id", models.PayloadSchemaType.KEYWORD)


def list_collections(client: QdrantClient) -> List[str]:
    names = [c.name for c in client.get_collections().collections]
    return sorted(n for n in names if n.startswith(COLLECTION_PREFIX))
