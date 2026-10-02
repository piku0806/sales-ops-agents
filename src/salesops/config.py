"""Central configuration, read from environment variables (or a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    llm_provider: str  # "mock" | "azure"
    azure_endpoint: str | None
    azure_api_key: str | None
    azure_deployment: str | None
    azure_api_version: str

    @property
    def crm_db(self) -> Path:
        return self.data_dir / "crm.db"

    @property
    def governance_db(self) -> Path:
        return self.data_dir / "governance.db"

    @property
    def audit_log(self) -> Path:
        return self.data_dir / "audit.jsonl"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def research_data(self) -> Path:
        return PROJECT_ROOT / "src" / "salesops" / "seed" / "company_research.json"


def get_settings() -> Settings:
    data_dir = Path(os.getenv("SALESOPS_DATA_DIR", PROJECT_ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        llm_provider=os.getenv("LLM_PROVIDER", "mock").lower(),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )
