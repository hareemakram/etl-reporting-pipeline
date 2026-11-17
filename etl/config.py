"""Runtime configuration, read from environment variables (12-factor style)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL", "postgresql+psycopg://etl:etl@localhost:5432/reporting"))
    raw_dir: Path = field(default_factory=lambda: Path(os.getenv("RAW_DATA_DIR", PROJECT_ROOT / "data" / "raw")))
    fixtures_dir: Path = field(default_factory=lambda: Path(
        os.getenv("FIXTURES_DIR", PROJECT_ROOT / "data" / "fixtures")))
    api_base_url: str = field(default_factory=lambda: os.getenv("API_BASE_URL", "http://localhost:8000/mock-api"))
    api_timeout_s: float = field(default_factory=lambda: _env_float("API_TIMEOUT_S", 5.0))
    api_max_retries: int = field(default_factory=lambda: int(os.getenv("API_MAX_RETRIES", "3")))
    # Price-drift warning threshold: |paid - list| / list above this is flagged.
    price_drift_threshold: float = field(default_factory=lambda: _env_float("PRICE_DRIFT_THRESHOLD", 0.35))

    @property
    def orders_dir(self) -> Path:
        return self.raw_dir / "orders"

    @property
    def customers_file(self) -> Path:
        return self.raw_dir / "customers.csv"


def get_settings() -> Settings:
    return Settings()
