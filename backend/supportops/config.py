import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(os.environ.get("SUPPORTOPS_PROJECT_ROOT", Path(__file__).resolve().parents[2]))


class ModelPrice(BaseModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPORTOPS_",
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )
    environment: Literal["development", "production"] = "development"
    seed_demo_data: bool = True
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "[::1]", "testserver"]
    )
    mode: Literal["demo", "live"] = "demo"
    database_url: str = Field(default="sqlite:///./var/supportops.db", repr=False)
    checkpoint_url: str = Field(default="sqlite:///./var/checkpoints.db", repr=False)
    auth_mode: Literal["demo", "oidc"] = "demo"
    auto_create_schema: bool = True
    worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=0.5, ge=0.1, le=60)
    api_key: str = Field(default="", repr=False)
    base_url: str = "https://api.openai.com/v1"
    small_model: str = "gpt-4.1-mini"
    reasoning_model: str = "gpt-4.1"
    fallback_model: str = ""
    fallback_base_url: str = ""
    fallback_api_key: str = Field(default="", repr=False)
    embedding_mode: Literal["auto", "local", "sentence_transformers"] = "auto"
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    local_embedding_revision: str = Field(
        default="1110a243fdf4706b3f48f1d95db1a4f5529b4d41", pattern=r"^[0-9a-f]{40}$"
    )
    local_embedding_cache: str = str(ROOT / "var" / "models")
    local_embedding_offline: bool = False
    embedding_model: str = "text-embedding-3-small"
    enable_guardrails: bool = False
    otlp_endpoint: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    request_deadline_seconds: int = Field(default=90, ge=10, le=600)
    max_tool_calls: int = Field(default=6, ge=1, le=12)
    model_output_tokens: int = Field(default=4000, ge=512, le=8192)
    model_call_timeout_seconds: int = Field(default=45, ge=5, le=120)
    max_context_tokens: int = Field(default=6000, ge=500, le=128000)
    model_context_window: int = Field(default=16000, ge=8192, le=2000000)
    fallback_context_window: int = Field(default=16000, ge=8192, le=2000000)
    approval_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_configuration(self):
        if not self.allowed_hosts:
            raise ValueError("At least one allowed host is required")
        if self.mode == "live" and not self.api_key:
            raise ValueError("Live mode requires SUPPORTOPS_API_KEY")
        if self.auth_mode == "oidc" and not all([self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url]):
            raise ValueError("OIDC requires issuer, audience and JWKS URL")
        if self.environment == "production":
            if "*" in self.allowed_hosts or "testserver" in self.allowed_hosts:
                raise ValueError(
                    "Production requires an explicit allowed_hosts list without wildcard or testserver"
                )
            if self.auth_mode != "oidc" or self.seed_demo_data or self.auto_create_schema:
                raise ValueError(
                    "Production requires OIDC, seed_demo_data=false and auto_create_schema=false"
                )
            if not all(url.startswith("postgresql") for url in (self.database_url, self.checkpoint_url)):
                raise ValueError("Production requires PostgreSQL for data and checkpoints")
            endpoints = [self.oidc_issuer, self.oidc_jwks_url]
            if self.mode == "live":
                endpoints.extend([self.base_url, self.fallback_base_url or self.base_url])
            if any(urlsplit(url).scheme != "https" or not urlsplit(url).hostname for url in endpoints):
                raise ValueError("Production identity and model endpoints must use HTTPS")
        return self
