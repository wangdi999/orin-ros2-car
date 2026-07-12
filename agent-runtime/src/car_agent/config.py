from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    agent_token: str = Field(default="development-only-token", alias="CAR_AGENT_TOKEN")
    agent_host: str = Field(default="0.0.0.0", alias="CAR_AGENT_HOST")
    agent_port: int = Field(default=8100, alias="CAR_AGENT_PORT")
    database_path: Path = Field(default=Path("data/agent.db"), alias="CAR_AGENT_DATABASE_PATH")
    checkpoint_path: Path = Field(
        default=Path("data/langgraph_checkpoints.db"),
        alias="CAR_AGENT_CHECKPOINT_PATH",
    )
    locations_path: Path = Field(
        default=Path("config/locations.yaml"),
        alias="CAR_AGENT_LOCATIONS_PATH",
    )
    policies_path: Path = Field(
        default=Path("config/policies.yaml"),
        alias="CAR_AGENT_POLICIES_PATH",
    )
    gateway_mode: Literal["mock", "rosbridge"] = Field(
        default="mock",
        alias="CAR_AGENT_GATEWAY_MODE",
    )

    llm_provider: Literal["mock", "openai_compatible"] = Field(
        default="mock",
        alias="LLM_PROVIDER",
    )
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_timeout_sec: float = Field(default=15.0, alias="LLM_TIMEOUT_SEC")

    cors_origins: str = Field(default="http://127.0.0.1:5173", alias="CAR_AGENT_CORS_ORIGINS")

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_data_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_data_directories()
    return settings
