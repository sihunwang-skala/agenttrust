from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("AGENTTRUST_DATABASE_URL", "sqlite:///./data/agenttrust.db"))
    key_dir: str = field(default_factory=lambda: os.environ.get("AGENTTRUST_KEY_DIR", "./data/keys"))
    cors_origins: list[str] = field(default_factory=lambda: os.environ.get(
        "AGENTTRUST_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    duplicate_window_seconds: int = field(default_factory=lambda: int(os.environ.get("AGENTTRUST_DUPLICATE_WINDOW_SECONDS", "30")))
    allow_demo_reset: bool = field(default_factory=lambda: _bool("AGENTTRUST_ALLOW_DEMO_RESET", False))

    def ensure_dirs(self) -> None:
        Path(self.key_dir).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
