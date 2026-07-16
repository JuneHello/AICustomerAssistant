"""
Application settings loaded from environment variables via Pydantic BaseSettings.

Usage:
    from config.settings import settings
    print(settings.POSTGRES_DSN)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the AI Customer Assistant."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── LLM Configuration ─────────────────────────────────────────────
    XIAOMI_MIMO_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="API key for Xiaomi MIMO models"
    )
    DEEPSEEK_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="API key for DeepSeek models"
    )
    PRIMARY_LLM: str = Field(
        default="xiaomi_mimo/mimo-v2.5", description="Primary model name for LiteLLM"
    )
    SMALL_LLM: str = Field(
        default="xiaomi_mimo/mimo-v2.5", description="Small/fallback model name for LiteLLM"
    )
    DEEPSEEK_BASE_URL: str = Field(
        default="https://api.deepseek.com/v1",
        description="Base URL for the DeepSeek-compatible API",
    )

    # ── MySQL (read-only, e-commerce data) ────────────────────────────
    MYSQL_DSN: str = Field(
        default="mysql+aiomysql://readonly:password@localhost:3306/ecommerce",
        description="Async MySQL DSN for the e-commerce database",
    )

    # ── PostgreSQL (primary store) ────────────────────────────────────
    POSTGRES_DSN: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_assistant",
        description="Async PostgreSQL DSN",
    )
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: SecretStr = Field(default="postgres")
    POSTGRES_DB: str = Field(default="ai_assistant")

    # ── Redis ─────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (with hiredis)",
    )

    # ── JWT Authentication ────────────────────────────────────────────
    JWT_SECRET_KEY: SecretStr = Field(
        ..., description="Secret key for JWT signing"
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRE_MINUTES: int = Field(
        default=1440, ge=1, description="Token expiration in minutes"
    )

    # ── Langfuse Observability ────────────────────────────────────────
    LANGFUSE_SECRET_KEY: SecretStr = Field(
        default=SecretStr(""), description="Langfuse secret key"
    )
    LANGFUSE_PUBLIC_KEY: str = Field(
        default="", description="Langfuse public key"
    )
    LANGFUSE_HOST: str = Field(
        default="http://localhost:3000",
        description="Langfuse server URL",
    )

    # ── Application ───────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    # ── Agent / RAG Tuning ────────────────────────────────────────────
    SESSION_TOKEN_BUDGET: int = Field(
        default=4096, ge=256, description="Max tokens per session context window"
    )
    MAX_TOOL_ITERATIONS: int = Field(
        default=10, ge=1, description="Max tool-call loops per agent turn"
    )
    RAG_TOP_K: int = Field(
        default=20, ge=1, description="Number of candidates from vector search"
    )
    RAG_RERANKER_THRESHOLD: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Reranker score cutoff"
    )
    RAG_FINAL_TOP_N: int = Field(
        default=5, ge=1, description="Final chunks sent to the LLM"
    )

    # ── Derived helpers ───────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def debug(self) -> bool:
        return self.APP_ENV == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    s = Settings()  # type: ignore[call-arg]
    
    # Export keys to os.environ for litellm
    import os
    if s.XIAOMI_MIMO_API_KEY and s.XIAOMI_MIMO_API_KEY.get_secret_value():
        os.environ["XIAOMI_MIMO_API_KEY"] = s.XIAOMI_MIMO_API_KEY.get_secret_value()
    if s.DEEPSEEK_API_KEY and s.DEEPSEEK_API_KEY.get_secret_value():
        os.environ["DEEPSEEK_API_KEY"] = s.DEEPSEEK_API_KEY.get_secret_value()
        
    # Export Langfuse environment variables
    if s.LANGFUSE_SECRET_KEY and s.LANGFUSE_SECRET_KEY.get_secret_value():
        os.environ["LANGFUSE_SECRET_KEY"] = s.LANGFUSE_SECRET_KEY.get_secret_value()
        os.environ["LANGFUSE_PUBLIC_KEY"] = s.LANGFUSE_PUBLIC_KEY
        os.environ["LANGFUSE_HOST"] = s.LANGFUSE_HOST
        
        # Configure litellm callbacks
        try:
            import litellm
            litellm.success_callback = ["langfuse"]
            litellm.failure_callback = ["langfuse"]
        except ImportError:
            pass
            
    return s


# Module-level convenience alias
settings: Settings = get_settings()
