import pytest

from its_parser.cli import db_name_from_url
from its_parser.downloader import clean_output_directory


def test_db_name_from_url():
    assert db_name_from_url("https://its.1c.ru/db/edtdoc") == "edtdoc"
    assert db_name_from_url("https://its.1c.ru/db/edtdoc/content/1/hdoc") == "edtdoc"
    assert db_name_from_url("https://its.1c.ru/db/edt_doc-2#content:1") == "edt_doc-2"


@pytest.mark.parametrize("url", [
    "https://its.1c.ru/db/..",
    "https://its.1c.ru/db/.",
    "https://its.1c.ru/db/a.b",
    "https://its.1c.ru/db/%2e%2e",
    "https://its.1c.ru/nodb",
])
def test_db_name_rejects_bad_urls(url):
    with pytest.raises(ValueError):
        db_name_from_url(url)


def test_clean_output_directory_inside_root(tmp_path):
    root = tmp_path / "out"
    target = root / "edtdoc"
    (target / "page_0001").mkdir(parents=True)
    clean_output_directory(str(target), str(root))
    assert target.is_dir() and not any(target.iterdir())


@pytest.mark.parametrize("rel", [".", "..", "../other", "out"])
def test_clean_output_directory_refuses_outside(tmp_path, rel):
    root = tmp_path / "out"
    root.mkdir()
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("x")
    with pytest.raises(ValueError):
        clean_output_directory(str(root / rel) if rel != "out" else str(root), str(root))
    assert sentinel.exists() and root.exists()


def test_clean_output_directory_refuses_symlink_escape(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        clean_output_directory(str(root / "link"), str(root))
    assert (outside / "keep.txt").exists()
