from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Common response metadata ---
class CMCStatus(BaseModel):
    timestamp: Optional[str] = None
    error_code: int = 0
    error_message: Optional[str] = None
    elapsed: Optional[int] = None
    credit_count: Optional[int] = None
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
    symbol: Optional[str] = None
    name: Optional[str] = None
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
    rwa_id: Optional[int] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    slug: Optional[str] = None
    asset_type: Optional[str] = None
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
    issuer_id: Optional[str] = None
    name: Optional[str] = None
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


# --- Single-issuer schemas (GET /v5/real-world-assets/issuers) ---
# The single-issuer endpoint does NOT return an `issuers` array like the list
# endpoint does. `data` is a FLAT issuer object with a top-level `tokens` list:
#   {"name": ..., "issuer_id": ..., "tokens": [{"symbol", "name", "crypto_id",
#     "rwa_id"}], "num_tokens": ..., "total_size": ..., "has_more": ...}
# Validating it with RWAIssuersResponse silently dropped `tokens` (Pydantic
# ignores unknown fields by default), which left the token->parent-RWA index
# empty and broke resolution of secondary symbols such as PAXG / XAUt.
class RWAIssuerToken(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: Optional[str] = None
    name: Optional[str] = None
    crypto_id: Optional[int] = None
    rwa_id: Optional[int] = None


class RWAIssuerDetailData(BaseModel):
    # extra="allow" so any field CMC adds later is preserved, not silently dropped.
    model_config = ConfigDict(extra="allow")

    issuer_id: Optional[str] = None
    name: Optional[str] = None
    website: Optional[str] = None
    logo: Optional[str] = None
    num_tokens: int = 0
    tokens: List[RWAIssuerToken] = Field(default_factory=list)
    total_size: int = 0
    has_more: bool = False


class RWAIssuerResponse(BaseModel):
    data: RWAIssuerDetailData
    status: CMCStatus


# --- Crypto & Global Market Schemas ---
class CryptoQuoteUSD(BaseModel):
    price: Optional[float] = None
    volume_24h: Optional[float] = None
    percent_change_24h: Optional[float] = None
    market_cap: Optional[float] = None
    last_updated: Optional[str] = None


class CryptoAssetData(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    quote: Dict[str, CryptoQuoteUSD] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_quote_field(cls, values: Any) -> Any:
        """
        The `quote` field is meant to be Dict[str, CryptoQuoteUSD] (e.g.
        {"USD": {...}}), but this API sometimes returns it as a bare list
        instead -- either a list containing one nested asset-like object
        (with its own 'quote' key) or a list containing the currency-quote
        fields directly. Normalize both shapes back into a proper dict
        keyed by currency (defaulting to "USD") before validation.
        """
        if not isinstance(values, dict) or "quote" not in values:
            return values

        quote_value = values.get("quote")
        if isinstance(quote_value, dict):
            return values

        values = dict(values)
        if isinstance(quote_value, list):
            if not quote_value:
                values["quote"] = {}
            else:
                first = quote_value[0]
                if isinstance(first, dict) and isinstance(first.get("quote"), (dict, list)):
                    # Nested asset-shaped entry; recurse one level.
                    nested = first["quote"]
                    if isinstance(nested, list):
                        nested = nested[0] if nested and isinstance(nested[0], dict) else {}
                    values["quote"] = nested if isinstance(nested, dict) else {}
                elif isinstance(first, dict) and any(k in first for k in ("USD", "EUR", "BTC")):
                    # Already keyed by currency.
                    values["quote"] = first
                elif isinstance(first, dict):
                    # Bare currency-quote fields (price, volume_24h, ...); assume USD.
                    values["quote"] = {"USD": first}
                else:
                    values["quote"] = {}
        else:
            values["quote"] = {}
        return values


def _normalize_crypto_quotes_data(value: Any) -> Any:
    """
    CMC's /v3/cryptocurrency/quotes/latest data field is inconsistent across
    response variants:
      - Usually a dict keyed by symbol: {"BTC": {...}}
      - Sometimes data[SYMBOL] itself is a list instead of a dict (duplicate
        tickers across chains/issuers): {"BTC": [{...}, {...}]}
      - Sometimes the whole `data` payload is a bare list of asset objects
        rather than being keyed by symbol at all: [{...}, {...}]

    Normalize all of these into a single Dict[str, dict] keyed by uppercase
    symbol, so Pydantic always sees a plain dict before validating each
    value as CryptoAssetData.
    """
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, entry in value.items():
            if isinstance(entry, list):
                normalized[key] = entry[0] if entry else {}
            else:
                normalized[key] = entry
        return normalized

    if isinstance(value, list):
        normalized = {}
        for entry in value:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol") or entry.get("id") or len(normalized)).upper()
            # Keep the first occurrence per symbol rather than overwriting.
            normalized.setdefault(symbol, entry)
        return normalized

    return value


class CryptoQuotesResponseData(BaseModel):
    data: Dict[str, CryptoAssetData] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_entries(cls, values: Any) -> Any:
        if isinstance(values, dict) and "data" in values:
            values = dict(values)
            values["data"] = _normalize_crypto_quotes_data(values.get("data"))
        return values


class CryptoQuotesResponse(BaseModel):
    data: Dict[str, CryptoAssetData] = Field(default_factory=dict)
    status: CMCStatus

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_entries(cls, values: Any) -> Any:
        if isinstance(values, dict) and "data" in values:
            values = dict(values)
            values["data"] = _normalize_crypto_quotes_data(values.get("data"))
        return values


class GlobalMetricsQuoteUSD(BaseModel):
    total_market_cap: Optional[float] = None
    total_volume_24h: Optional[float] = None
    last_updated: Optional[str] = None


class GlobalMetricsData(BaseModel):
    btc_dominance: Optional[float] = None
    eth_dominance: Optional[float] = None
    active_cryptocurrencies: Optional[int] = None
    quote: Dict[str, GlobalMetricsQuoteUSD] = Field(default_factory=dict)


class GlobalMetricsResponse(BaseModel):
    data: GlobalMetricsData
    status: CMCStatus


class CMCResponseEnvelope(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)
    status: CMCStatus
