import asyncio
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from qdrant_client import QdrantClient

from its_parser.rag.config import Settings
from its_parser.rag.indexer import index_db
from its_parser.rag.server import create_server

from test_rag_index_search import FakeEmbedder

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def env(tmp_path):
    settings = replace(Settings.from_env(), out_dir=tmp_path / "out", qdrant_path=Path(":memory:"))
    d = settings.out_dir / "edtdoc"
    for src, name in (("0003", "page_0001"), ("0009", "page_0002"), ("0011", "page_0003")):
        shutil.copytree(FIXTURES / f"page_{src}", d / name)
    # фикстура 0009 — со свежим metadata.json, остальные — со старым metadata.txt
    client = QdrantClient(":memory:")
    embedder = FakeEmbedder()
    index_db("edtdoc", settings, client, embedder)
    yield settings, client, embedder
    client.close()


def call(env, tool, **args):
    settings, client, embedder = env

    async def run():
        async with Client(create_server(settings, client=client, embedder=embedder)) as c:
            return await c.call_tool(tool, args)

    return asyncio.run(run()).data


def call_error(env, tool, **args):
    with pytest.raises(ToolError) as exc:
        call(env, tool, **args)
    return str(exc.value)


def test_tools_have_russian_docs(env):
    settings, client, embedder = env

    async def run():
        async with Client(create_server(settings, client=client, embedder=embedder)) as c:
            return await c.list_tools()

    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == {"search_docs", "get_page", "list_sections", "list_databases"}
    for t in tools.values():
        assert t.description and any("а" <= ch <= "я" for ch in t.description.lower())


def test_search_docs(env):
    hits = call(env, "search_docs", query="системные требования процессор оперативная память", db="edtdoc")
    top = hits[0]
    assert top["page_id"] == "page_0002" and top["db"] == "edtdoc"
    assert top["url"].endswith("/content/39/hdoc")
    assert top["breadcrumbs"] == ["Начало", "Установка, обновление"]
    assert top["title"] == "Системные требования"
    assert not top["fragment"].startswith("Раздел:")
    assert top["cite"] == "Системные требования (1.2.1.1) — https://its.1c.ru/db/edtdoc/content/39/hdoc"
    old = call(env, "search_docs", query="Обзор возможностей плагины", db="edtdoc")
    assert all(h["cite"].endswith(h["url"]) for h in old)  # номера нет (metadata.txt) — без скобок
    assert len({h["page_id"] for h in hits}) == len(hits)


def test_search_docs_limit_and_validation(env):
    assert len(call(env, "search_docs", query="EDT", limit=1)) == 1
    assert len(call(env, "search_docs", query="EDT", limit=1000)) <= 20
    assert "Пустой" in call_error(env, "search_docs", query="  ")
    assert "Недопустимое" in call_error(env, "search_docs", query="x", db="../etc")
    assert "не проиндексирована" in call_error(env, "search_docs", query="x", db="nope")


def test_get_page(env):
    page = call(env, "get_page", db="edtdoc", page_id="page_0002")
    assert page["title"] == "Системные требования"
    assert page["number"] == "1.2.1.1."
    assert "| Процессор | Intel Core i3 |" in page["markdown"]
    assert "](/db/edtdoc" in page["markdown"] or "](https://" in page["markdown"]  # ссылки сохранены
    code = call(env, "get_page", db="edtdoc", page_id="page_0003")
    assert "```\n1ce-installer-cli install\n```" in code["markdown"]


def test_get_page_truncation(env):
    full = call(env, "get_page", db="edtdoc", page_id="page_0002")
    assert full["truncated"] is False and full["total_chars"] == len(full["markdown"]) > 5000
    cut = call(env, "get_page", db="edtdoc", page_id="page_0002", max_chars=3000)
    assert cut["truncated"] is True and cut["total_chars"] == full["total_chars"]
    assert 2100 <= len(cut["markdown"]) <= 3000
    assert full["markdown"].startswith(cut["markdown"])
    tiny = call(env, "get_page", db="edtdoc", page_id="page_0002", max_chars=1)  # нижняя граница 500
    assert 350 <= len(tiny["markdown"]) <= 500 and tiny["truncated"] is True


@pytest.mark.parametrize("db,page_id", [
    ("edtdoc", "../page_0001"),
    ("edtdoc", "page_0001/../../edtdoc/page_0002"),
    ("edtdoc", "/etc/passwd"),
    ("edtdoc", "page_0001\x00"),
    ("edtdoc", ".."),
    ("..", "page_0001"),
    ("edtdoc/..", "page_0001"),
    ("a.b", "page_0001"),
])
def test_get_page_rejects_traversal(env, db, page_id):
    assert "Недопустим" in call_error(env, "get_page", db=db, page_id=page_id)


def test_get_page_symlink_escape(env, tmp_path):
    settings = env[0]
    outside = tmp_path / "secret"
    shutil.copytree(FIXTURES / "page_0003", outside)
    (settings.out_dir / "edtdoc" / "page_0099").symlink_to(outside)
    assert "Недопустим" in call_error(env, "get_page", db="edtdoc", page_id="page_0099")


def test_get_page_not_found(env):
    assert "не найдена" in call_error(env, "get_page", db="edtdoc", page_id="page_0777")
    assert "не найдена" in call_error(env, "get_page", db="other", page_id="page_0001")


def test_list_sections(env):
    allp = call(env, "list_sections", db="edtdoc")
    assert [p["page_id"] for p in allp] == ["page_0001", "page_0002", "page_0003"]
    assert allp[1] == {
        "number": "1.2.1.1.", "title": "Системные требования", "level": 5,
        "page_id": "page_0002", "url": "https://its.1c.ru/db/edtdoc/content/39/hdoc",
    }
    assert [p["page_id"] for p in call(env, "list_sections", db="edtdoc", prefix="1.2")] == ["page_0002"]
    assert [p["page_id"] for p in call(env, "list_sections", db="edtdoc", prefix="1.2.1.1.")] == ["page_0002"]
    assert call(env, "list_sections", db="edtdoc", prefix="1.20") == []
    assert call(env, "list_sections", db="edtdoc", prefix="1.") != []
    assert "не найдена" in call_error(env, "list_sections", db="nope")
    assert "Недопустимое" in call_error(env, "list_sections", db="../x")


def test_list_databases(env):
    dbs = call(env, "list_databases")
    assert len(dbs) == 1
    assert dbs[0]["db"] == "edtdoc" and dbs[0]["pages"] == 3 and dbs[0]["chunks"] > 3
