from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API Key (Optional)")
    CMC_BASE_URL: str = Field(default="https://pro-api.coinmarketcap.com")
    CMC_TIMEOUT_SECONDS: float = Field(default=10.0)

    # Rate limiting: the free Startup tier granted for this hackathon allows
    # 30 requests/minute. We throttle client-side to stay under that instead
    # of relying on catching 429s after the fact. Override via .env if your
    # plan differs.
    CMC_RATE_LIMIT_PER_MINUTE: int = Field(
        default=30, description="Max outbound CMC API calls allowed per rolling 60s window."
    )

    # Retry/backoff for transient failures (429 rate limit, 5xx upstream errors).
    CMC_MAX_RETRIES: int = Field(default=3, description="Retries for 429/5xx responses.")
    CMC_RETRY_BACKOFF_BASE_SECONDS: float = Field(
        default=1.0, description="Base delay for exponential backoff between retries."
    )

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()