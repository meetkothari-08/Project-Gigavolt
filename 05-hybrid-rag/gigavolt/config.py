"""Central runtime configuration.

Every service endpoint, credential and filesystem path is read from the
environment (optionally via a `.env` file in the working directory). Nothing
is hard-coded, so the same code runs on a laptop, a single EC2 host, or the
two-server layout used in production (vector/document server + RAG server).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "intfloat/e5-small-v2"
EMBEDDING_DIMENSIONS = 384


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


@dataclass(frozen=True)
class MariaDBSettings:
    host: str = field(default_factory=lambda: _env("MARIADB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("MARIADB_PORT", 3306))
    user: str | None = field(default_factory=lambda: _env("MARIADB_USER"))
    password: str | None = field(default_factory=lambda: _env("MARIADB_PASSWORD"))
    database: str = field(default_factory=lambda: _env("MARIADB_DATABASE", "gigavolt"))


@dataclass(frozen=True)
class MongoDBSettings:
    host: str = field(default_factory=lambda: _env("MONGODB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("MONGODB_PORT", 27017))
    username: str | None = field(default_factory=lambda: _env("MONGODB_USERNAME"))
    password: str | None = field(default_factory=lambda: _env("MONGODB_PASSWORD"))
    database: str = field(default_factory=lambda: _env("MONGODB_DATABASE", "sensorDB"))
    collection: str = field(default_factory=lambda: _env("MONGODB_COLLECTION", "telemetry"))


@dataclass(frozen=True)
class VectorSettings:
    chroma_host: str = field(default_factory=lambda: _env("CHROMA_HOST", "127.0.0.1"))
    chroma_port: int = field(default_factory=lambda: _env_int("CHROMA_PORT", 8000))
    collection: str = field(
        default_factory=lambda: _env("CHROMA_COLLECTION", "gigavolt_m4_final")
    )
    embedding_api_url: str = field(
        default_factory=lambda: _env("EMBEDDING_API_URL", "http://127.0.0.1:8001/embed")
    )


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str = field(
        default_factory=lambda: _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "phi:latest"))
    timeout: int = field(default_factory=lambda: _env_int("OLLAMA_TIMEOUT", 180))


@dataclass(frozen=True)
class PathSettings:
    """Filesystem layout. All paths default to folders under the repo root."""

    data_dir: Path = field(
        default_factory=lambda: Path(_env("GIGAVOLT_DATA_DIR", "data")).resolve()
    )
    state_dir: Path = field(
        default_factory=lambda: Path(_env("GIGAVOLT_STATE_DIR", "var/state")).resolve()
    )
    log_dir: Path = field(
        default_factory=lambda: Path(_env("GIGAVOLT_LOG_DIR", "var/logs")).resolve()
    )

    @property
    def documents_dir(self) -> Path:
        return Path(_env("GIGAVOLT_DOCUMENTS_DIR", str(self.data_dir / "documents")))

    @property
    def processed_dir(self) -> Path:
        return Path(_env("GIGAVOLT_PROCESSED_DIR", str(self.data_dir / "processed")))

    @property
    def chroma_dir(self) -> Path:
        return Path(_env("GIGAVOLT_CHROMA_DIR", str(self.data_dir / "chroma_store")))


@dataclass(frozen=True)
class Settings:
    mariadb: MariaDBSettings = field(default_factory=MariaDBSettings)
    mongodb: MongoDBSettings = field(default_factory=MongoDBSettings)
    vector: VectorSettings = field(default_factory=VectorSettings)
    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    paths: PathSettings = field(default_factory=PathSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings, read once from the environment."""
    return Settings()
