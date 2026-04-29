from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "QuizForge"
    debug: bool = True
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    mongo_dsn: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "testing_system"
    access_cookie_name: str = "access_token"
    refresh_cookie_name: str = "refresh_token"
    host: str = "0.0.0.0"
    port: int = 8000
    report_storage_dir: Path = Field(default=BASE_DIR / "storage" / "reports")
    upload_storage_dir: Path = Field(default=BASE_DIR / "storage" / "uploads")

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.report_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
