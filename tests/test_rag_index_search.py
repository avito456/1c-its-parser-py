import hashlib
import math
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

from its_parser.rag.cli import discover_dbs
from its_parser.rag.config import Settings
from its_parser.rag.indexer import chunk_point_id, index_db
from its_parser.rag.search import search
from its_parser.rag.store import DENSE, SPARSE, list_collections

FIXTURES = Path(__file__).parent / "fixtures"
DIM = 64


def _tokens(text):
    return re.findall(r"\w+", text.lower())


def _bucket(token, mod):
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % mod


class FakeEmbedder:
    """Детерминированный bag-of-words эмбеддер: без скачивания моделей"""
    dense_dim = DIM

    def _dense(self, text):
        v = [0.0] * DIM
        for t in _tokens(text):
            v[_bucket(t, DIM)] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def _sparse(self, text):
        counts = {}
        for t in _tokens(text):
            counts[_bucket(t, 100_000)] = counts.get(_bucket(t, 100_000), 0) + 1.0
        return models.SparseVector(indices=list(counts), values=list(counts.values()))

    def embed_passages(self, texts):
        return [self._dense(t) for t in texts], [self._sparse(t) for t in texts]

    def embed_query(self, query):
        return self._dense(query), self._sparse(query)


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(), out_dir=tmp_path / "out", qdrant_path=Path(":memory:"))


@pytest.fixture
def db_dir(settings):
    d = settings.out_dir / "edtdoc"
    for src, name in (("0003", "page_0001"), ("0009", "page_0002"), ("0011", "page_0003")):
        shutil.copytree(FIXTURES / f"page_{src}", d / name)
    return d


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    yield c
    c.close()


def count(client, collection="its_edtdoc"):
    return client.count(collection, exact=True).count


def test_index_creates_collection_with_named_vectors(settings, db_dir, client):
    stats = index_db("edtdoc", settings, client, FakeEmbedder())
    assert (stats.pages_total, stats.pages_indexed, stats.pages_skipped) == (3, 3, 0)
    assert stats.chunks == count(client) > 3
    info = client.get_collection("its_edtdoc").config.params
    assert info.vectors[DENSE].size == DIM
    assert info.sparse_vectors[SPARSE].modifier == models.Modifier.IDF
    pts, _ = client.scroll("its_edtdoc", limit=1, with_payload=True)
    payload = pts[0].payload
    for key in ("db", "page_id", "title", "breadcrumbs", "url", "heading", "chunk_idx",
                "content_hash", "chunk_count", "text"):
        assert key in payload
    assert pts[0].id == chunk_point_id("edtdoc", payload["page_id"], payload["chunk_idx"])


def test_reindex_skips_unchanged_pages(settings, db_dir, client):
    first = index_db("edtdoc", settings, client, FakeEmbedder())
    second = index_db("edtdoc", settings, client, FakeEmbedder())
    assert (second.pages_indexed, second.pages_skipped, second.chunks) == (0, 3, 0)
    assert count(client) == first.chunks


def test_changed_page_reindexed_removed_page_deleted(settings, db_dir, client):
    index_db("edtdoc", settings, client, FakeEmbedder())
    page = db_dir / "page_0003" / "page.html"
    page.write_text(page.read_text(encoding="utf-8").replace("install", "uninstall"), encoding="utf-8")
    shutil.rmtree(db_dir / "page_0002")
    stats = index_db("edtdoc", settings, client, FakeEmbedder())
    assert (stats.pages_indexed, stats.pages_skipped, stats.pages_deleted) == (1, 1, 1)
    pages = {p.payload["page_id"] for p in client.scroll("its_edtdoc", limit=1000, with_payload=True)[0]}
    assert pages == {"page_0001", "page_0003"}
    hit = search(client, FakeEmbedder(), settings, "uninstall", db="edtdoc")[0]
    assert hit.page_id == "page_0003"


def test_incomplete_page_is_reindexed(settings, db_dir, client):
    stats = index_db("edtdoc", settings, client, FakeEmbedder())
    victim = chunk_point_id("edtdoc", "page_0001", 0)
    client.delete("its_edtdoc", points_selector=models.PointIdsList(points=[victim]))
    again = index_db("edtdoc", settings, client, FakeEmbedder())
    assert again.pages_indexed == 1 and count(client) == stats.chunks


def test_reindex_flag_recreates(settings, db_dir, client):
    index_db("edtdoc", settings, client, FakeEmbedder())
    stats = index_db("edtdoc", settings, client, FakeEmbedder(), reindex=True)
    assert stats.pages_indexed == 3 and stats.pages_skipped == 0


def test_dimension_mismatch_requires_reindex(settings, db_dir, client):
    index_db("edtdoc", settings, client, FakeEmbedder())
    other = FakeEmbedder()
    other.dense_dim = DIM * 2
    with pytest.raises(RuntimeError, match="--reindex"):
        index_db("edtdoc", settings, client, other)


def test_search_hybrid_finds_relevant_page(settings, db_dir, client):
    index_db("edtdoc", settings, client, FakeEmbedder())
    emb = FakeEmbedder()
    hits = search(client, emb, settings, "системные требования процессор оперативная память", db="edtdoc")
    assert hits[0].page_id == "page_0002"
    assert hits[0].url.endswith("/content/39/hdoc")
    assert hits[0].breadcrumbs == ["Начало", "Установка, обновление"]
    hits = search(client, emb, settings, "1ce-installer-cli install --source", db="edtdoc")
    assert hits[0].page_id == "page_0003"


def test_search_dedup_and_all_collections(settings, db_dir, client):
    other = settings.out_dir / "other"
    shutil.copytree(db_dir, other)
    emb = FakeEmbedder()
    index_db("edtdoc", settings, client, emb)
    index_db("other", settings, client, emb)
    assert list_collections(client) == ["its_edtdoc", "its_other"]

    query = "1C:EDT платформа версии Java"
    plain = search(client, emb, settings, query, limit=10, dedup=False)
    dedup = search(client, emb, settings, query, limit=10)
    assert {h.db for h in dedup} == {"edtdoc", "other"}
    keys = [(h.db, h.page_id) for h in dedup]
    assert len(keys) == len(set(keys))
    assert len(plain) > len(dedup)
    assert {h.db for h in search(client, emb, settings, query, db="other")} == {"other"}


def test_search_unknown_db(settings, client):
    with pytest.raises(ValueError):
        search(client, FakeEmbedder(), settings, "x", db="nope")


def test_discover_dbs(settings, db_dir):
    (settings.out_dir / "empty").mkdir()
    assert discover_dbs(settings.out_dir) == ["edtdoc"]
    assert discover_dbs(settings.out_dir / "missing") == []


@pytest.mark.slow
def test_real_models_end_to_end(settings, db_dir, client):
    from its_parser.rag.store import FastEmbedder

    small = replace(settings, dense_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    emb = FastEmbedder(small)
    index_db("edtdoc", small, client, emb)
    hits = search(client, emb, small, "какие нужны процессор и память", db="edtdoc")
    assert hits[0].page_id == "page_0002"
