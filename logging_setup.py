from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Union

from loguru import logger


def setup_logging(
    stdout_level: str = "INFO",
    log_file: Optional[Union[str, Path]] = None,
    log_file_level: str = "DEBUG",
) -> None:
    """Настраивает loguru: отдельный sink для stdout и опциональный sink для файла."""
    logger.remove()

    logger.add(
        sys.stderr,
        level=stdout_level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            str(log_path),
            level=log_file_level.upper(),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}",
            rotation="10 MB",
            retention="10 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
        )
