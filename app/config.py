from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql:///recovery_meeting_ingestion_dev",
        alias="DATABASE_URL",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    user_agent: str = Field(
        default="SoberSpaceRecoveryMeetingIngestion/0.1 (+https://soberspace.app)",
        alias="USER_AGENT",
    )
    default_rate_limit_seconds: float = Field(default=1.0, alias="DEFAULT_RATE_LIMIT_SECONDS")
    snapshot_output_dir: Path = Field(default=Path("snapshots"), alias="SNAPSHOT_OUTPUT_DIR")
    geocoder_provider: str | None = Field(default=None, alias="GEOCODER_PROVIDER")
    geocoder_api_key: str | None = Field(default=None, alias="GEOCODER_API_KEY")


def get_settings() -> Settings:
    return Settings()
