from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration class for application environment variables,
    API keys, timeouts, and model defaults.
    """

    # --- API Keys ---
    CMC_API_KEY: str = Field(
        ..., 
        description="CoinMarketCap Pro API Key (Required)"
    )
    OPENAI_API_KEY: str = Field(
        ..., 
        description="OpenAI API Key for the LangGraph agent (Required)"
    )
    SERVER_API_KEY: Optional[str] = Field(
        default=None,
        description="Static API key guard for FastAPI endpoints (Optional in dev)"
    )

    # --- Server Configuration ---
    PORT: int = Field(default=8000, description="FastAPI server port")
    ENVIRONMENT: str = Field(default="development", description="App environment")

    # --- CoinMarketCap Settings ---
    CMC_BASE_URL: str = Field(
        default="https://pro-api.coinmarketcap.com",
        description="Base URL for CoinMarketCap Pro API"
    )
    CMC_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="HTTP request timeout in seconds"
    )

    # --- Agent Configuration ---
    LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model identifier for agent reasoning"
    )

    # --- Cache Configuration ---
    CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL duration for in-memory market data caching (5 mins)"
    )

    # --- Pydantic Settings Setup ---
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Global instantiated settings singleton
settings = Settings()