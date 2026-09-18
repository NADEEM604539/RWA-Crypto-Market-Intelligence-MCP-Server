from app.tools.resolve_rwa_asset import resolve_rwa_asset
from app.tools.get_rwa_market_quote import get_rwa_market_quote
from app.tools.compare_rwa_vs_crypto import compare_rwa_vs_crypto
from app.tools.get_rwa_issuers_info import get_rwa_issuers_info
from app.tools.get_global_market_metrics import get_global_market_metrics

# Centralized export registry for all LangChain tools
ALL_TOOLS = [
    resolve_rwa_asset,
    get_rwa_market_quote,
    compare_rwa_vs_crypto,
    get_rwa_issuers_info,
    get_global_market_metrics,
]