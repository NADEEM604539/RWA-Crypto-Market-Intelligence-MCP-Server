from typing import Any, Dict
from app.cmc.client import cmc_client


async def get_rwa_issuers_info(limit: int = 50) -> Dict[str, Any]:
    """
    Fetches the verified list of official Real-World Asset (RWA) token issuers 
    (e.g., Backed Assets, Backpack, Paxos, Tether) and token counts managed.
    
    Args:
        limit: Number of issuers to retrieve (default: 50, max: 250).
    """
    try:
        data = await cmc_client.get_rwa_issuers_list(limit=limit)
        issuers = data.get("issuers", [])

        formatted_issuers = [
            {
                "issuer_id": issuer.get("issuer_id"),
                "name": issuer.get("name"),
                "website": issuer.get("website"),
                "num_tokens": issuer.get("num_tokens"),
            }
            for issuer in issuers
        ]

        return {
            "total_issuers_tracked": data.get("total_size", len(formatted_issuers)),
            "count_returned": len(formatted_issuers),
            "issuers": formatted_issuers,
        }
    except Exception as e:
        return {"error": f"Failed to fetch RWA issuers info: {str(e)}"}