from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    CMC_API_KEY: str = Field(..., description="CoinMarketCap API Key")
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API Key (Optional)")
    
    CMC_BASE_URL: str = Field(default="https://pro-api.coinmarketcap.com")
    CMC_TIMEOUT_SECONDS: float = Field(default=10.0)

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()