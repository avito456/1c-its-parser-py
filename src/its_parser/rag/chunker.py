from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from its_parser.rag.extract import PageInfo, extract_page, load_page_info

MAX_CHARS = 1200
OVERLAP = 150
MAX_PREFIX_PATH = 300  # длинный путь разделов обрезается слева, чтобы не съедать бюджет чанка
CHUNKER_VERSION = 2  # входит в хэш страницы: смена алгоритма вызывает переиндексацию

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Chunk:
    text: str  # с префиксом «Раздел: ...» — именно он эмбеддится
    db: str
    page_id: str
    number: str
    title: str
    breadcrumbs: List[str]
    url: str
    heading: str
    chunk_idx: int

    def payload(self) -> dict:
        return asdict(self)


def split_sections(markdown: str) -> List[Tuple[str, str]]:
    """Режет markdown по заголовкам h1–h4 (вне fenced-блоков): [(heading, body_with_heading_line)]"""
    sections: List[Tuple[str, List[str]]] = [("", [])]
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            sections.append((match.group(2), [line]))
        else:
            sections[-1][1].append(line)
    result = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        # раздел из одного заголовка без текста индексировать нечего
        if body and not (heading and body == lines[0].strip()):
            result.append((heading, body))
    return result


def _hard_split(text: str, max_chars: int) -> List[str]:
    """Режет слишком длинный абзац (код, таблица) по строкам, затем по словам"""
    pieces: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > max_chars:
            cut = line.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _paragraphs(body: str, max_chars: int) -> List[str]:
    """Абзацы по пустым строкам; fenced-код не рвём по пустым строкам внутри"""
    paragraphs: List[str] = []
    current: List[str] = []
    in_fence = False
    for line in body.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    result: List[str] = []
    for p in paragraphs:
        result.extend(_hard_split(p, max_chars) if len(p) > max_chars else [p])
    return result


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    # начинаем с границы слова, чтобы не обрезать слово посередине
    return tail[space + 1:] if 0 <= space < len(tail) - 1 else tail


def split_body(body: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> List[str]:
    """Собирает абзацы в куски до max_chars; следующий кусок начинается с хвоста предыдущего"""
    overlap = min(overlap, max_chars // 4)
    pieces: List[str] = []
    current = ""
    # абзац + перекрытие + разделитель «\n\n» всегда укладываются в max_chars
    for para in _paragraphs(body, max_chars - overlap - 2):
        candidate = para if not current else f"{current}\n\n{para}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        pieces.append(current)
        tail = _overlap_tail(current, overlap)
        current = f"{tail}\n\n{para}" if tail else para
    if current:
        pieces.append(current)
    return pieces


def section_path(info: PageInfo, heading: str) -> str:
    """Крошки > заголовок страницы > подзаголовок; повторы (в т.ч. h1, входящий в заголовок) опускаются"""
    parts: List[str] = []
    for part in (*info.breadcrumbs, info.title):
        if part and (not parts or part != parts[-1]):
            parts.append(part)
    if heading and not any(heading.casefold() in p.casefold() for p in parts):
        parts.append(heading)
    path = " > ".join(parts)
    if len(path) > MAX_PREFIX_PATH:
        tail = path[-MAX_PREFIX_PATH:]
        # режем по границе уровня, если она есть
        path = "… > " + tail.split(" > ", 1)[1] if " > " in tail else "…" + tail
    return path


_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((?:[^()\s]|\([^()]*\))*(?:\s+\"[^\"]*\")?\)")
_LIST_NOISE = set("-*+0123456789.;,: \n")


def _compress_link_blocks(markdown: str) -> str:
    """Абзацы и списки только из ссылок (оглавления) → «Подразделы: A; B; C»"""
    blocks: List[str] = []
    current: List[str] = []
    in_fence = False

    def close() -> None:
        if current:
            blocks.append("\n".join(current))
            current.clear()

    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            close()
            blocks.append("")
        else:
            current.append(line)
    close()

    out = []
    for block in blocks:
        links = _LINK_RE.findall(block) if block and "```" not in block else []
        rest = _LINK_RE.sub("", block)
        if len(links) >= 2 and set(rest) <= _LIST_NOISE:
            titles = [" ".join(t.split()) for t in links if t.strip()]
            block = "Подразделы: " + "; ".join(titles)
        out.append(block)
    return "\n".join(out)


def prepare_for_index(markdown: str) -> str:
    """Текст для индекса: оглавления сжимаются, [текст](url) → текст (картинки остаются)"""
    text = _compress_link_blocks(markdown)
    text = _LINK_RE.sub(lambda m: " ".join(m.group(1).split()), text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_markdown(markdown: str, info: PageInfo, db: str,
                   max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> List[Chunk]:
    chunks: List[Chunk] = []
    for heading, body in split_sections(prepare_for_index(markdown)):
        prefix = f"Раздел: {section_path(info, heading)}\n\n"
        for piece in split_body(body, max_chars - len(prefix), overlap):
            chunks.append(Chunk(
                text=prefix + piece,
                db=db,
                page_id=info.page_id,
                number=info.number,
                title=info.title,
                breadcrumbs=list(info.breadcrumbs),
                url=info.url,
                heading=heading or info.title,
                chunk_idx=len(chunks),
            ))
    return chunks


def chunk_page(page_dir: Path, db: str, info: Optional[PageInfo] = None, **kwargs) -> List[Chunk]:
    page_dir = Path(page_dir)
    info = info or load_page_info(page_dir)
    return chunk_markdown(extract_page(page_dir), info, db, **kwargs)
