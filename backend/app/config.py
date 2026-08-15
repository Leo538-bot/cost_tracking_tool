from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://tripcost:tripcost@db:5432/tripcost"

    # Signing key for session tokens. MUST be overridden in production.
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    # Vacation sessions should outlive the trip so nobody gets logged out mid-dinner.
    session_days: int = 90

    upload_dir: Path = Path("/data/receipts")
    # Receipts are photos of paper slips; anything past this is a mistake or an attack.
    max_upload_bytes: int = 12 * 1024 * 1024
    # Long edge of the stored image. Enough to read a slip, small enough for mobile data.
    image_max_edge: int = 2000
    thumbnail_max_edge: int = 400
    jpeg_quality: int = 82

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
