from __future__ import annotations


class DocPage:
    """Класс для хранения информации о странице документации"""

    def __init__(self, url: str, title: str, level: int = 0, number: str = "") -> None:
        self.url: str = url
        self.title: str = title
        self.level: int = level
        self.number: str = number

    def __str__(self) -> str:
        return f"{self.number} {'  ' * self.level}{self.title}"