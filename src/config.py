from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql://postgres:postgres@postgres:5432/adsintel",
        alias="DATABASE_URL",
    )
    use_fixtures: bool = Field(default=False, alias="USE_FIXTURES")
    meta_api_token: str = Field(default="", alias="META_API_TOKEN")
    tiktok_api_key: str = Field(default="", alias="TIKTOK_API_KEY")
    microsoft_api_key: str = Field(default="", alias="MICROSOFT_API_KEY")
    ingestion_interval_minutes: int = Field(default=15, alias="INGESTION_INTERVAL_MINUTES")
    inactive_after_days: int = Field(default=30, alias="INACTIVE_AFTER_DAYS")

    model_config = {"extra": "ignore"}


settings = Settings()
