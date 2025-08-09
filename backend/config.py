"""Configuration management for AI Code Reviewer."""

from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings."""

    # GitHub App Configuration
    github_app_id: int
    github_app_private_key_path: str
    github_webhook_secret: str

    # Database Configuration
    database_url: str

    # PostgreSQL Configuration (used by docker-compose)
    postgres_user: Optional[str] = None
    postgres_password: Optional[str] = None
    postgres_db: Optional[str] = None

    # Redis Configuration
    redis_url: str

    # AI Model Configuration
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    huggingface_token: Optional[str] = None

    # App Configuration
    app_name: str = "AI Code Reviewer"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str

    # Celery Configuration
    celery_broker_url: str
    celery_result_backend: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


# Create a global instance
settings = get_settings()
