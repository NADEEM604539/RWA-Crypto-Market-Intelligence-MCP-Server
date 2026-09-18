import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_chat, routes_health, routes_tools
from app.cmc.client import cmc_client
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan Context Manager.
    Handles startup (initializing persistent clients) and shutdown (cleanup) events.
    """
    # --- Startup Logic ---
    print(f"🚀 Starting RWA & Crypto Intelligence Server [{settings.ENVIRONMENT}]")
    # Initialize the underlying httpx AsyncClient connection pool
    _ = cmc_client.client

    yield

    # --- Shutdown Logic ---
    print("🛑 Shutting down server and closing active connection pools...")
    await cmc_client.close()


# Initialize core FastAPI Application Instance
app = FastAPI(
    title="RWA & Crypto Market Intelligence API",
    description=(
        "Production-grade intelligence gateway leveraging CoinMarketCap Pro API "
        "to deliver real-time metrics on tokenized real-world assets (RWAs) and cryptocurrencies."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Set up Cross-Origin Resource Sharing (CORS) for UI integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production environments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Route Handlers
app.include_router(routes_health.router, tags=["Health"])
app.include_router(routes_chat.router, prefix="/api/v1", tags=["Agent Chat"])
app.include_router(routes_tools.router, prefix="/api/v1/tools", tags=["Direct Tools"])


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=(settings.ENVIRONMENT == "development"),
    )