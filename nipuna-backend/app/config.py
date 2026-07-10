import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]

ENV_TO_FIELD = {
    "DATABASE_URL": "database_url",
    "ENV": "env",
    "AWS_REGION": "aws_region",
    "AWS_SECRETS_MANAGER_SECRET_NAME": "aws_secrets_manager_secret_name",
    "CLERK_SECRET_KEY": "clerk_secret_key",
    "CLERK_WEBHOOK_SECRET": "clerk_webhook_secret",
    "CLERK_DOMAIN": "clerk_domain",
    "CLERK_PUBLISHABLE_KEY": "clerk_publishable_key",
    "GROQ_API_KEY": "groq_api_key",
    "REDIS_URL": "redis_url",
    "CELERY_BROKER_URL": "celery_broker_url",
    "OPENAI_API_KEY": "openai_api_key",
    "COMPOSIO_API_KEY": "composio_api_key",
    "RAZORPAY_KEY_ID": "razorpay_key_id",
    "RAZORPAY_KEY_SECRET": "razorpay_key_secret",
    "RAZORPAY_WEBHOOK_SECRET": "razorpay_webhook_secret",
    "RAZORPAY_PLAN_STARTER": "razorpay_plan_starter",
    "RAZORPAY_PLAN_GROWTH": "razorpay_plan_growth",
    "RAZORPAY_PLAN_ENTERPRISE": "razorpay_plan_enterprise",
    "RESEND_API_KEY": "resend_api_key",
    "META_WHATSAPP_TOKEN": "meta_whatsapp_token",
    "META_PHONE_NUMBER_ID": "meta_phone_number_id",
    "SENTRY_DSN": "sentry_dsn",
    "ENCRYPTION_KEY": "encryption_key",
    "LLM_PROVIDER": "llm_provider",
    "GROQ_MODEL": "groq_model",
    "OPENSEARCH_ENDPOINT": "opensearch_endpoint",
    "GSTN_API_KEY": "gstn_api_key",
    "FRONTEND_URL": "frontend_url",
    "COMPOSIO_REDIRECT_URL": "composio_redirect_url",
    "TALLY_MCP_BASE_URL": "tally_mcp_base_url",
    "CORS_EXTRA_ORIGINS": "cors_extra_origins",
    "N8N_BASE_URL": "n8n_base_url",
    "N8N_API_KEY": "n8n_api_key",
    "N8N_TIMEOUT_SECONDS": "n8n_timeout_seconds",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/nipuna_ai",
        alias="DATABASE_URL",
    )
    env: str = Field(default="dev", alias="ENV")
    aws_region: str = Field(default="ap-south-1", alias="AWS_REGION")
    aws_secrets_manager_secret_name: str | None = Field(
        default=None,
        alias="AWS_SECRETS_MANAGER_SECRET_NAME",
    )
    clerk_secret_key: str | None = Field(default=None, alias="CLERK_SECRET_KEY")
    clerk_webhook_secret: str | None = Field(default=None, alias="CLERK_WEBHOOK_SECRET")
    clerk_domain: str = Field(default="", alias="CLERK_DOMAIN")
    clerk_publishable_key: str = Field(
        default="",
        alias="CLERK_PUBLISHABLE_KEY",
    )
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    composio_api_key: str | None = Field(default=None, alias="COMPOSIO_API_KEY")
    razorpay_key_id: str | None = Field(default=None, alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str | None = Field(default=None, alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str | None = Field(default=None, alias="RAZORPAY_WEBHOOK_SECRET")
    razorpay_plan_starter: str | None = Field(default=None, alias="RAZORPAY_PLAN_STARTER")
    razorpay_plan_growth: str | None = Field(default=None, alias="RAZORPAY_PLAN_GROWTH")
    razorpay_plan_enterprise: str | None = Field(default=None, alias="RAZORPAY_PLAN_ENTERPRISE")
    resend_api_key: str | None = Field(default=None, alias="RESEND_API_KEY")
    meta_whatsapp_token: str | None = Field(default=None, alias="META_WHATSAPP_TOKEN")
    meta_phone_number_id: str | None = Field(default=None, alias="META_PHONE_NUMBER_ID")
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    encryption_key: str | None = Field(default=None, alias="ENCRYPTION_KEY")
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    opensearch_endpoint: str | None = Field(default=None, alias="OPENSEARCH_ENDPOINT")
    gstn_api_key: str | None = Field(default=None, alias="GSTN_API_KEY")
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")
    composio_redirect_url: str | None = Field(default=None, alias="COMPOSIO_REDIRECT_URL")
    tally_mcp_base_url: str | None = Field(default=None, alias="TALLY_MCP_BASE_URL")
    cors_extra_origins: str = Field(default="", alias="CORS_EXTRA_ORIGINS")
    n8n_base_url: str = Field(default="http://localhost:5678", alias="N8N_BASE_URL")
    n8n_api_key: str | None = Field(default=None, alias="N8N_API_KEY")
    n8n_timeout_seconds: float = Field(default=20.0, alias="N8N_TIMEOUT_SECONDS")

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")

    @property
    def effective_celery_broker_url(self) -> str:
        if self.celery_broker_url:
            return self.celery_broker_url
        if self.is_production:
            return "sqs://"
        return self.redis_url

    def validate_auth_config(self) -> None:
        missing = []
        if not self.clerk_domain:
            missing.append("CLERK_DOMAIN")
        if not self.clerk_secret_key:
            missing.append("CLERK_SECRET_KEY")
        if missing:
            logger.warning(
                "Missing authentication configuration: %s. Auth checks and Clerk endpoints will fail.",
                ", ".join(missing),
            )


def load_secrets_from_aws(settings: Settings) -> dict[str, str]:
    secret_name = settings.aws_secrets_manager_secret_name or os.getenv("AWS_SECRETS_MANAGER_SECRET_NAME")
    if not secret_name:
        return {}

    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Unable to load secrets from AWS Secrets Manager: %s", exc)
        return {}

    secret_string = response.get("SecretString")
    if not secret_string:
        return {}

    try:
        secret_payload = json.loads(secret_string)
    except json.JSONDecodeError:
        logger.warning("Secrets Manager payload was not valid JSON for secret '%s'.", secret_name)
        return {}

    loaded: dict[str, str] = {}
    for env_key, field_name in ENV_TO_FIELD.items():
        secret_value = secret_payload.get(env_key)
        if secret_value in (None, ""):
            continue
        if getattr(settings, field_name, None) not in (None, ""):
            continue
        loaded[field_name] = str(secret_value)

    return loaded


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        aws_overrides = load_secrets_from_aws(settings)
        if aws_overrides:
            settings = settings.model_copy(update=aws_overrides)
    settings.validate_auth_config()
    return settings
