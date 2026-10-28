"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@db:5432/meetings"
    app_timezone: str = "Europe/Kyiv"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    run_migrations_on_start: bool = True
    version: str = Field(default="1.0.0")

    # Cognito user pool whose access tokens the API accepts. Empty pool id means
    # authentication is not configured, and every meetings request is refused.
    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    # The pool's signing keys (JSON, or that JSON base64-encoded). The Lambda
    # runs in a VPC without internet access, so the deploy passes them in; when
    # empty they are fetched from Cognito on first use.
    cognito_jwks: str = ""

    # The agenda parser's model (Lab 6). "anthropic" is the Anthropic Messages API
    # on Bedrock (bedrock-mantle, model ids like anthropic.claude-opus-5-5),
    # "converse" is the Bedrock Converse API (e.g.
    # us.anthropic.claude-haiku-4-5-20251001-v1:0), "anthropic_api" is the Claude
    # API directly (model ids like claude-opus-5-5), and "fake" calls no model.
    parser_provider: Literal["anthropic", "converse", "anthropic_api", "fake"] = "anthropic"
    parser_model: str = "anthropic.claude-opus-5-5"
    parser_region: str = "us-east-1"
    # For "anthropic_api" in Lambda: the SSM SecureString holding the API key.
    # Empty (locally) means the SDK reads ANTHROPIC_API_KEY from the environment.
    anthropic_api_key_parameter: str = ""
    # Longer pasted text is refused (413) before any model is called.
    parser_max_chars: int = 10_000

    @field_validator("app_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)  # raises for an unknown timezone
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def parser_model_id(self) -> str:
        """The model that answers, as logged and stored: "fake" when none is called."""
        return "fake" if self.parser_provider == "fake" else self.parser_model

    @property
    def cognito_issuer(self) -> str:
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
