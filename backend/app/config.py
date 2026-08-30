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

    # Header carrying the real visitor address, set by the reverse proxy. Only
    # trustworthy because the API port is never published -- nginx is the sole
    # peer that can reach it. Set to "" to fall back to the socket address.
    client_ip_header: str = "x-real-ip"

    # The interactive API docs list every endpoint and schema. Handy locally,
    # needless exposure once the app is reachable from the internet.
    docs_enabled: bool = False

    # Anything shorter is brute-forcible, and PyJWT itself warns below 32 bytes.
    min_jwt_secret_length: int = 32

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_secrets(self) -> list[str]:
        """Report configuration that would make the deployment forgeable."""
        problems = []
        if self.jwt_secret == Settings.model_fields["jwt_secret"].default:
            problems.append(
                "JWT_SECRET is still the built-in default. Anyone who reads the "
                "source can mint valid sessions. Set it to a random value, e.g. "
                "`openssl rand -base64 32`."
            )
        elif len(self.jwt_secret.encode()) < self.min_jwt_secret_length:
            problems.append(
                f"JWT_SECRET is only {len(self.jwt_secret.encode())} bytes; "
                f"at least {self.min_jwt_secret_length} are required."
            )
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
