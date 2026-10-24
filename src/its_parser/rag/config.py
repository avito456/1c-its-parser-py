from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_DENSE_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_SPARSE_MODEL = "Qdrant/bm25"


@dataclass(frozen=True)
class Settings:
    """Настройки RAG-подсистемы; значения по умолчанию переопределяются через ITS_*"""

    out_dir: Path = Path("out")
    data_dir: Path = Path("data")
    qdrant_path: Path = Path("data") / "qdrant"
    qdrant_url: Optional[str] = None
    dense_model: str = DEFAULT_DENSE_MODEL
    sparse_model: str = DEFAULT_SPARSE_MODEL
    models_cache: Optional[Path] = None

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        data_dir = Path(env.get("ITS_DATA_DIR") or "data")
        cache = env.get("ITS_MODELS_CACHE")
        return cls(
            out_dir=Path(env.get("ITS_OUT_DIR") or "out"),
            data_dir=data_dir,
            qdrant_path=Path(env.get("ITS_QDRANT_PATH") or data_dir / "qdrant"),
            qdrant_url=env.get("ITS_QDRANT_URL") or None,
            dense_model=env.get("ITS_DENSE_MODEL") or DEFAULT_DENSE_MODEL,
            sparse_model=env.get("ITS_SPARSE_MODEL") or DEFAULT_SPARSE_MODEL,
            models_cache=Path(cache) if cache else (data_dir / "models" if env.get("ITS_DATA_DIR") else None),
        )

    @property
    def passage_prefix(self) -> str:
        # fastembed не добавляет префиксы для e5 сам: их нужно задавать вручную
        return "passage: " if "e5" in self.dense_model.lower() else ""

    @property
    def query_prefix(self) -> str:
        return "query: " if "e5" in self.dense_model.lower() else ""

    def collection_name(self, db: str) -> str:
        return f"its_{db}"

    def db_dir(self, db: str) -> Path:
        return self.out_dir / db
