import asyncio

from app.cmc.client import cmc_client
from app.tools.compare_rwa_vs_crypto import compare_rwa_vs_crypto
from app.tools.resolve_rwa_asset import resolve_rwa_asset


def test_resolve_rwa_asset_accepts_token_symbol(monkeypatch):
    async def fake_get_rwa_quotes(symbol=None, rwa_id=None):
        if symbol == "PAXG":
            raise ValueError("Invalid parameter")
        assert rwa_id == "1"
        return {"rwa_assets": [{
            "rwa_id": 1,
            "symbol": "GOLD",
            "name": "Gold",
            "slug": "gold",
            "asset_type": "commodity",
            "rwa_rank": 1,
            "has_tokens": True,
        }]}

    async def fake_get_rwa_issuers_list(limit=250, start=1):
        return {
            "issuers": [{"issuer_id": "issuer-1"}],
            "has_more": False,
        }

    async def fake_get_rwa_issuer(issuer_id, limit=100, start=1):
        return {"tokens": [{"symbol": "PAXG", "name": "PAX Gold", "rwa_id": 1}]}

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)
    monkeypatch.setattr(cmc_client, "get_rwa_issuer", fake_get_rwa_issuer)

    result = asyncio.run(resolve_rwa_asset("PAXG"))

    assert result["symbol"] == "GOLD"
    assert result["resolved_via"] == "token_symbol"
    assert result["rwa_id"] == 1


def test_compare_rwa_vs_crypto_accepts_tokenized_rwa_symbol(monkeypatch):
    async def fake_get_rwa_quotes(symbol=None, rwa_id=None):
        if rwa_id == "1":
            return {
                "rwa_assets": [{
                    "symbol": "GOLD",
                    "name": "Gold",
                    "asset_type": "commodity",
                    "quotes": [{
                        "average_tokenized_price": 3000,
                        "tokenized_market_cap": 1000000000,
                        "tokenized_volume_24h": 50000000,
                    }],
                    "tokens": [{"symbol": "PAXG", "name": "PAX Gold"}],
                }]
            }
        if symbol == "PAXG":
            return {"rwa_assets": []}
        raise AssertionError(f"Unexpected symbol: {symbol}")

    async def fake_get_rwa_issuers_list(limit=250, start=1):
        return {"issuers": [{"issuer_id": "issuer-1"}], "has_more": False}

    async def fake_get_rwa_issuer(issuer_id, limit=100, start=1):
        return {"tokens": [{"symbol": "PAXG", "name": "PAX Gold", "rwa_id": 1}]}

    async def fake_get_crypto_quotes(symbol):
        assert symbol == "BTC"
        return {
            "BTC": {
                "symbol": "BTC",
                "name": "Bitcoin",
                "quote": {
                    "USD": {
                        "price": 60000,
                        "market_cap": 1200000000000,
                        "volume_24h": 50000000000,
                        "percent_change_24h": 2.5,
                    }
                },
            }
        }

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)
    monkeypatch.setattr(cmc_client, "get_rwa_issuer", fake_get_rwa_issuer)
    monkeypatch.setattr(cmc_client, "get_crypto_quotes", fake_get_crypto_quotes)

    result = asyncio.run(compare_rwa_vs_crypto("PAXG", "BTC"))

    assert "error" not in result
    assert result["rwa_asset"]["symbol"] == "GOLD"
    assert result["crypto_asset"]["symbol"] == "BTC"


def test_compare_rwa_vs_crypto_handles_list_payloads(monkeypatch):
    async def fake_get_rwa_quotes(symbol=None, rwa_id=None):
        if rwa_id == "1":
            return [{
                "rwa_id": 1,
                "symbol": "GOLD",
                "name": "Gold",
                "asset_type": "commodity",
                "quotes": [{
                    "average_tokenized_price": 3000,
                    "tokenized_market_cap": 1000000000,
                    "tokenized_volume_24h": 50000000,
                }],
                "tokens": [{"symbol": "PAXG", "name": "PAX Gold"}],
            }]
        if symbol == "PAXG":
            return []
        raise AssertionError(f"Unexpected symbol: {symbol}")

    async def fake_get_rwa_issuers_list(limit=250, start=1):
        return {"issuers": [{"issuer_id": "issuer-1"}], "has_more": False}

    async def fake_get_rwa_issuer(issuer_id, limit=100, start=1):
        return {"tokens": [{"symbol": "PAXG", "name": "PAX Gold", "rwa_id": 1}]}

    async def fake_get_crypto_quotes(symbol):
        assert symbol == "BTC"
        return {
            "BTC": {
                "symbol": "BTC",
                "name": "Bitcoin",
                "quote": {
                    "USD": {
                        "price": 60000,
                        "market_cap": 1200000000000,
                        "volume_24h": 50000000000,
                        "percent_change_24h": 2.5,
                    }
                },
            }
        }

    monkeypatch.setattr(cmc_client, "get_rwa_quotes", fake_get_rwa_quotes)
    monkeypatch.setattr(cmc_client, "get_rwa_issuers_list", fake_get_rwa_issuers_list)
    monkeypatch.setattr(cmc_client, "get_rwa_issuer", fake_get_rwa_issuer)
    monkeypatch.setattr(cmc_client, "get_crypto_quotes", fake_get_crypto_quotes)

    result = asyncio.run(compare_rwa_vs_crypto("PAXG", "BTC"))

    assert "error" not in result
    assert result["rwa_asset"]["symbol"] == "GOLD"
    assert result["crypto_asset"]["symbol"] == "BTC"
