from pathlib import Path

import pytest

from its_parser.rag.chunker import (
    MAX_CHARS, Chunk, chunk_markdown, chunk_page, prepare_for_index, section_path, split_body,
    split_sections,
)
from its_parser.rag.config import Settings
from its_parser.rag.extract import PageInfo, extract_page, html_to_markdown, load_page_info

FIXTURES = Path(__file__).parent / "fixtures"


def page(n: str) -> Path:
    return FIXTURES / f"page_{n}"


def test_extract_drops_scripts_styles_and_head():
    md = extract_page(page("0003"))
    assert md.startswith("# Обзор возможностей")
    for junk in ("onBodyAvailable", "<script", "DITA Open Toolkit", "font-family", "<style"):
        assert junk not in md


def test_extract_cover_page():
    md = extract_page(page("0001"))
    assert "# 1C:Enterprise Development Tools" in md
    assert "Руководство разработчика" in md
    assert "adjustContentLegacy" not in md


def test_extract_keeps_table():
    md = extract_page(page("0009"))
    assert "| Процессор | Intel Core i3 | Intel Core i5 |" in md
    assert "| --- |" in md


def test_extract_keeps_code_blocks():
    md = extract_page(page("0011"))
    assert "```\n1ce-installer-cli install\n```" in md
    assert "1ce-installer-cli install --source C:\\dist\\dist1" in md


def test_extract_images_relative_icons_dropped():
    md = extract_page(page("0004"))
    assert "](img/image002.png)" in md
    assert "image001.png" not in md  # иконки 16x16 (якоря заголовков)
    assert "http" not in md.split("](img/image002.png)")[0].splitlines()[-1]


def test_extract_unwraps_anchor_links_keeps_external():
    md = extract_page(page("0003"))
    assert "(#i005" not in md
    assert "[Установка, обновление](/db/edtdoc/content/10384/hdoc)" in md


def test_html_to_markdown_inline():
    md = html_to_markdown(
        "<html><head><title>x</title></head><body><nav>menu</nav>"
        "<h2>T</h2><p>a&nbsp;b</p><pre><code>x = 1</code></pre></body></html>"
    )
    assert "menu" not in md and "x</title>" not in md
    assert "## T" in md and "a b" in md and "x = 1" in md


def test_load_page_info_json_and_txt_fallback():
    info = load_page_info(page("0009"))
    assert info.page_id == "page_0009"
    assert info.number == "1.2.1.1."
    assert info.breadcrumbs == ["Начало", "Установка, обновление"]
    old = load_page_info(page("0003"))
    assert old.title == "Возможности"
    assert old.url == "https://its.1c.ru/db/edtdoc/content/5/hdoc"
    assert old.breadcrumbs == []


def test_split_sections_ignores_headings_in_fences():
    md = "# A\n\ntext\n\n```\n# not heading\n```\n\n## B\n\nmore\n\n### Empty\n"
    sections = split_sections(md)
    assert [h for h, _ in sections] == ["A", "B"]
    assert "# not heading" in sections[0][1]


def test_chunks_have_prefix_and_metadata():
    chunks = chunk_page(page("0009"), db="edtdoc")
    assert chunks
    first = chunks[0]
    assert isinstance(first, Chunk)
    assert first.text.startswith("Раздел: Начало > Установка, обновление > Системные требования\n\n")
    assert first.payload() == {
        "text": first.text, "db": "edtdoc", "page_id": "page_0009", "number": "1.2.1.1.",
        "title": "Системные требования", "breadcrumbs": ["Начало", "Установка, обновление"],
        "url": "https://its.1c.ru/db/edtdoc/content/39/hdoc",
        "heading": first.heading, "chunk_idx": 0,
    }
    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))
    sub = [c for c in chunks if c.heading == "Минимальный профиль работы"]
    assert sub and sub[0].text.startswith(
        "Раздел: Начало > Установка, обновление > Системные требования > Минимальный профиль работы\n\n"
    )


def test_chunk_size_limits_and_overlap():
    chunks = chunk_page(page("0003"), db="edtdoc")
    assert len(chunks) > 3
    for c in chunks:
        assert len(c.text) <= MAX_CHARS  # вместе с префиксом «Раздел: ...»
    long_text = " ".join(f"слово{i}" for i in range(600))
    pieces = split_body(long_text.replace(" ", "\n\n", 1) + "\n\n" + "\n\n".join(
        f"Абзац номер {i}. " + "текст " * 40 for i in range(10)), 1200, 150)
    assert len(pieces) > 2
    for prev, nxt in zip(pieces, pieces[1:]):
        tail = prev[-60:]
        assert tail.split()[-1] in nxt[:400]


def test_oversized_code_block_is_split():
    code = "```\n" + "\n".join(f"line {i} " + "x" * 50 for i in range(100)) + "\n```"
    info = PageInfo(page_id="p", title="T")
    chunks = chunk_markdown(f"# T\n\n{code}", info, db="d")
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)


def test_budget_holds_for_long_prefix_and_big_overlap():
    info = PageInfo(page_id="p", title="Т" * 200, breadcrumbs=["Раздел " + "К" * 150] * 3)
    text = "# H\n\n" + "\n\n".join("слово " * 60 for _ in range(30))
    chunks = chunk_markdown(text, info, db="d")
    assert len(chunks) > 3
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert all(c.text.startswith("Раздел: ") for c in chunks)
    assert len(chunks[0].text.split("\n\n", 1)[0]) <= 320


def test_links_become_plain_text_images_kept():
    md = "См. [Установка\nEDT](/db/edtdoc/content/1/hdoc) и ![схема](img/a.png), [x](https://a.b/c_(d)) тут."
    out = prepare_for_index(md)
    assert out == "См. Установка EDT и ![схема](img/a.png), x тут."


def test_link_only_blocks_are_compressed():
    md = (
        "# Раздел\n\nВведение.\n\n"
        "- [Первый](/a)\n- [Второй](/b)\n  - [Вложенный](/c)\n\n"
        "[Один](/x)\n\n"
        "[А](/1); [Б](/2)\n\n"
        "Смесь: [ссылка](/y) и текст\n"
    )
    out = prepare_for_index(md)
    assert "Подразделы: Первый; Второй; Вложенный" in out
    assert "Подразделы: А; Б" in out
    assert "\n\nОдин\n\n" in out  # одиночная ссылка — обычный текст
    assert "Смесь: ссылка и текст" in out
    assert "(/" not in out


def test_toc_page_chunks_have_no_urls():
    chunks = chunk_page(page("0003"), db="edtdoc")
    assert not any("](" in c.text and "![" not in c.text for c in chunks)


def test_section_path_dedups_root():
    info = PageInfo(page_id="p", title="1C:Enterprise Development Tools Руководство разработчика")
    assert section_path(info, "1C:Enterprise Development Tools") == info.title
    assert section_path(info, "") == info.title
    info = PageInfo(page_id="p", title="Начало", breadcrumbs=["Начало"])
    assert section_path(info, "Начало") == "Начало"
    info = PageInfo(page_id="p", title="Т", breadcrumbs=["А", "Б"])
    assert section_path(info, "Раздел") == "А > Б > Т > Раздел"


def test_settings_defaults_and_prefixes(monkeypatch):
    for var in ("ITS_DATA_DIR", "ITS_QDRANT_PATH", "ITS_QDRANT_URL", "ITS_DENSE_MODEL",
                "ITS_SPARSE_MODEL", "ITS_MODELS_CACHE", "ITS_OUT_DIR"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.dense_model == "intfloat/multilingual-e5-large"
    assert s.sparse_model == "Qdrant/bm25"
    assert s.qdrant_path == Path("data/qdrant") and s.qdrant_url is None
    assert s.models_cache == Path("data/models")
    assert (s.query_prefix, s.passage_prefix) == ("query: ", "passage: ")
    assert s.collection_name("edtdoc") == "its_edtdoc"

    monkeypatch.setenv("ITS_DATA_DIR", "/srv/its")
    monkeypatch.setenv("ITS_DENSE_MODEL", "BAAI/bge-small-en-v1.5")
    s = Settings.from_env()
    assert s.qdrant_path == Path("/srv/its/qdrant")
    assert s.models_cache == Path("/srv/its/models")
    monkeypatch.setenv("ITS_MODELS_CACHE", "/cache")
    assert Settings.from_env().models_cache == Path("/cache")
    assert s.query_prefix == "" and s.passage_prefix == ""
