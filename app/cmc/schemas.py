from typing import List, Optional
from pydantic import BaseModel, Field


# --- Standard CMC Status Meta Header ---
class CMCStatus(BaseModel):
    timestamp: str
    error_code: int
    error_message: Optional[str] = ""
    elapsed: int
    credit_count: int
    notice: Optional[str] = None


# --- Real-World Asset (RWA) Schemas ---
class RWAQuoteUSD(BaseModel):
    symbol: str = Field(default="USD")
    crypto_id: Optional[int] = None
    average_tokenized_price: Optional[float] = None
    tokenized_market_cap: Optional[float] = None
    tokenized_volume_24h: Optional[float] = None
    last_updated: Optional[str] = None


class RWATokenDetail(BaseModel):
    symbol: str
    name: str
    price: Optional[float] = None
    crypto_id: Optional[int] = None
    issuer_id: Optional[str] = None
    issuer_name: Optional[str] = None
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None


class TradFiExchange(BaseModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    exchange_id: Optional[int] = None


class TradFiMarket(BaseModel):
    exchange: Optional[TradFiExchange] = None
    ticker: Optional[str] = None
    market_url: Optional[str] = None


class RWAAsset(BaseModel):
    rwa_id: int
    name: str
    symbol: str
    slug: str
    asset_type: str
    rwa_rank: Optional[int] = None
    has_tokens: bool = True
    average_tokenized_price: Optional[float] = None
    tokenized_market_cap: Optional[float] = None
    tokenized_volume_24h: Optional[float] = None
    last_updated: Optional[str] = None
    quotes: List[RWAQuoteUSD] = Field(default_factory=list)
    tokens: List[RWATokenDetail] = Field(default_factory=list)
    tradfi_markets: List[TradFiMarket] = Field(default_factory=list)


class RWAQuotesResponseData(BaseModel):
    rwa_assets: List[RWAAsset] = Field(default_factory=list)


class RWAQuotesResponse(BaseModel):
    data: RWAQuotesResponseData
    status: CMCStatus


# --- Issuer Schemas ---
class RWAIssuer(BaseModel):
    issuer_id: str
    name: str
    website: Optional[str] = None
    logo: Optional[str] = None
    num_tokens: int = 0


class RWAIssuersResponseData(BaseModel):
    issuers: List[RWAIssuer] = Field(default_factory=list)
    total_size: int = 0
    has_more: bool = False


class RWAIssuersResponse(BaseModel):
    data: RWAIssuersResponseData
    status: CMCStatus


# --- Crypto & Global Market Schemas ---
class CryptoQuoteUSD(BaseModel):
    price: float
    volume_24h: float
    percent_change_24h: Optional[float] = None
    market_cap: float
    last_updated: Optional[str] = None


class CryptoAssetData(BaseModel):
    id: int
    name: str
    symbol: str
    quote: dict  # Contains dict mapping currency e.g., {"USD": CryptoQuoteUSD}


class GlobalMetricsQuoteUSD(BaseModel):
    total_market_cap: float
    total_volume_24h: float
    last_updated: Optional[str] = None


class GlobalMetricsData(BaseModel):
    btc_dominance: float
    eth_dominance: float
    active_cryptocurrencies: int
    quote: dict