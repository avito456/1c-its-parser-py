from __future__ import annotations

from typing import List


class DocPage:
    """Класс для хранения информации о странице документации"""

    def __init__(self, url: str, title: str, level: int = 0, number: str = "") -> None:
        self.url: str = url
        self.title: str = title
        self.level: int = level
        self.number: str = number
        self.breadcrumbs: List[str] = []

    def __str__(self) -> str:
        return f"{self.number} {'  ' * self.level}{self.title}"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "level": self.level,
            "number": self.number,
            "url": self.url,
            "breadcrumbs": list(self.breadcrumbs),
        }


def assign_breadcrumbs(pages: List[DocPage]) -> None:
    """Заполняет breadcrumbs: заголовки родителей по иерархии уровней"""
    stack: List[DocPage] = []
    for page in pages:
        while stack and stack[-1].level >= page.level:
            stack.pop()
        page.breadcrumbs = [p.title for p in stack]
        stack.append(page)
