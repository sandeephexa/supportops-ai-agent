import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(os.environ.get("SUPPORTOPS_PROJECT_ROOT", Path(__file__).resolve().parents[2]))


class ModelPrice(BaseModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPORTOPS_", env_file=".env", extra="ignore", env_ignore_empty=True
    )
    mode: Literal["demo", "live"] = "demo"
    database_url: str = "sqlite:///./var/supportops.db"
    checkpoint_url: str = "sqlite:///./var/checkpoints.db"
    auth_mode: Literal["demo", "oidc"] = "demo"
    auto_create_schema: bool = True
    worker_enabled: bool = True
    worker_poll_seconds: float = 0.5
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    small_model: str = "gpt-4.1-mini"
    reasoning_model: str = "gpt-4.1"
    fallback_model: str = ""
    fallback_base_url: str = ""
    fallback_api_key: str = ""
    embedding_mode: Literal["auto", "local"] = "auto"
    embedding_model: str = "text-embedding-3-small"
    enable_guardrails: bool = False
    otlp_endpoint: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    request_deadline_seconds: int = 90
    max_tool_calls: int = 6
    model_output_tokens: int = Field(default=4000, ge=512, le=8192)
    model_call_timeout_seconds: int = Field(default=45, ge=5, le=120)
    max_context_tokens: int = 6000
    model_context_window: int = 16000
    fallback_context_window: int = 16000
    approval_ttl_seconds: int = 3600
    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.mode == "live" and not self.api_key:
            raise ValueError("Live mode requires SUPPORTOPS_API_KEY")
        if self.auth_mode == "oidc" and not all([self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url]):
            raise ValueError("OIDC requires issuer, audience and JWKS URL")
        return self
