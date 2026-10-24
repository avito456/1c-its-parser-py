from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

_JUNK_TAGS = ("script", "style", "noscript", "iframe", "nav", "link", "meta", "template")
_ICON_MAX_SIZE = 24  # px: мелкие картинки (иконки-якоря) в текст не попадают


class _Converter(MarkdownConverter):
    def convert_a(self, el, text, parent_tags=None, **kwargs):
        href = el.get("href") or ""
        # внутристраничные якоря бесполезны вне браузера: оставляем только текст
        if href.startswith("#") or not text.strip():
            return text
        return super().convert_a(el, text, parent_tags=parent_tags, **kwargs)

    # списки определений (dl/dt/dd) — обычные абзацы, а не расширение «:   » из PHP Markdown Extra
    def convert_dl(self, el, text, parent_tags=None, **kwargs):
        return f"\n\n{text.strip()}\n\n"

    def convert_dt(self, el, text, parent_tags=None, **kwargs):
        return f"\n\n**{text.strip()}**\n\n" if text.strip() else ""

    def convert_dd(self, el, text, parent_tags=None, **kwargs):
        return f"\n\n{text.strip()}\n\n"

    def convert_div(self, el, text, parent_tags=None, **kwargs):
        return f"\n\n{text.strip()}\n\n" if text.strip() else ""


def html_to_markdown(html: str) -> str:
    """page.html → markdown только с телом статьи; таблицы и pre/code сохраняются"""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    for tag in body.find_all(_JUNK_TAGS):
        tag.decompose()
    for img in body.find_all("img"):
        if _is_icon(img):
            img.decompose()

    text = _Converter(
        heading_style="ATX",
        bullets="-",
        code_language="",
        strip=["span", "font"],
    ).convert_soup(body)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _is_icon(img) -> bool:
    for attr in ("width", "height"):
        value = re.match(r"\d+", str(img.get(attr, "")))
        if value and int(value.group()) <= _ICON_MAX_SIZE:
            return True
    return False


@dataclass
class PageInfo:
    page_id: str
    title: str = ""
    level: int = 0
    number: str = ""
    url: str = ""
    breadcrumbs: List[str] = field(default_factory=list)


def load_page_info(page_dir: Path) -> PageInfo:
    """metadata.json, а для страниц, скачанных старой версией, — metadata.txt"""
    page_dir = Path(page_dir)
    info = PageInfo(page_id=page_dir.name)
    json_path = page_dir / "metadata.json"
    txt_path = page_dir / "metadata.txt"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        info.title = data.get("title", "")
        info.level = int(data.get("level", 0))
        info.number = data.get("number", "")
        info.url = data.get("url", "")
        info.breadcrumbs = list(data.get("breadcrumbs", []))
    elif txt_path.exists():
        for line in txt_path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            value = value.strip()
            if key == "Title":
                info.title = value
            elif key == "Level":
                info.level = int(value) if value.isdigit() else 0
            elif key == "URL":
                info.url = value
    return info


def extract_page(page_dir: Path) -> str:
    return html_to_markdown((Path(page_dir) / "page.html").read_text(encoding="utf-8"))
