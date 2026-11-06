"""Environment-driven application settings.

All values are validated at startup; the process refuses to boot with an
invalid configuration. Env vars are prefixed ``TOCKB_`` to avoid collisions.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.enums import MaxDepthStrategy, Paradigm


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings are validated by Pydantic; an invalid value causes the
    process to refuse to boot. Use ``get_settings()`` (cached) rather than
    instantiating directly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TOCKB_",
        case_sensitive=False,
        extra="ignore",
    )

    # Persistence
    database_url: PostgresDsn
    redis_url: str = "redis://localhost:6379/0"

    # Tree invariants
    max_depth: int = Field(default=5, ge=1, le=10)
    max_alias_hops: int = Field(default=3, ge=1, le=10)
    max_tokens_per_node: int = Field(default=50_000, gt=0)
    max_variance_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Routing behaviour
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    max_depth_strategy: MaxDepthStrategy = MaxDepthStrategy.SPILLOVER

    # Restructuring / audit
    kmeans_max_clusters: int = Field(default=7, ge=2, le=20)
    audit_interval_days: int = Field(default=30, ge=1)
    audit_sample_size: int = Field(default=10, ge=1, le=100)
    audit_batch_size: int = Field(default=100, ge=1, le=1000)

    # Embeddings
    embedding_dimensions: Literal[1536, 3072] = 1536
    embedding_model: str = "text-embedding-3-large"
    embedding_provider: Literal["openai", "local"] = "openai"

    # LLM
    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"

    # Phase 4 -- audit + aliases
    alias_discovery_enabled: bool = True
    alias_similarity_threshold: float = Field(
        default=0.80, ge=0.0, le=1.0
    )
    admin_token: SecretStr | None = None

    # Defaults
    default_paradigm: Paradigm = Paradigm.THEMATIC

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use in DI; never call ``Settings()`` directly."""
    return Settings()  # type: ignore[call-arg]
