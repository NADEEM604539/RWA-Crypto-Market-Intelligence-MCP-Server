# Remote MCP Server Connection Guide

This guide explains how to connect AI clients and developer tools to the deployed CoinMarketCap RWA & Crypto Intelligence MCP server.

## 1. Deployed endpoint

The live server is available at:

- **MCP endpoint:** `https://cmcserver.fastmcp.app/mcp`
- **Transport:** HTTP / SSE via MCP remote bridge
- **Auth header:** `X-CMC_PRO_API_KEY`

---

## 2. Authentication contract

Every client request must send the following header:

```http
X-CMC_PRO_API_KEY: your_coinmarketcap_api_key_here
```

This is the required request metadata for access to the server's live tool suite.

> Do not commit production keys into source control. Store them in a secret manager or local environment variables.

---

## 3. Claude Desktop setup

Claude Desktop typically runs local stdio processes, so the remote HTTPS endpoint is bridged through `mcp-remote`.

### Configuration file

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

### Example config

```json
{
  "mcpServers": {
    "coinmarketcap": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://cmcserver.fastmcp.app/mcp",
        "--header",
        "X-CMC_PRO_API_KEY:${CMC_API_KEY}"
      ],
      "env": {
        "CMC_API_KEY": "your_coinmarketcap_api_key_here"
      }
    }
  }
}
```

### Windows note

If `npx` is not in `PATH`, use the full Node executable path.

```json
{
  "command": "D:\\node-v20.19.1-win-x64\\node-v20.19.1-win-x64\\npx.cmd"
}
```

---

## 4. Cursor IDE setup

1. Open **Cursor Settings**.
2. Go to **Features -> MCP Servers**.
3. Click **Add New MCP Server**.
4. Use the following command:

```bash
npx mcp-remote https://cmcserver.fastmcp.app/mcp --header "X-CMC_PRO_API_KEY:your_coinmarketcap_api_key_here"
```

---

## 5. Python client example

```python
import asyncio
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

SERVER_URL = "https://cmcserver.fastmcp.app/mcp"
API_KEY = "your_coinmarketcap_api_key_here"

async def main():
    headers = {"X-CMC_PRO_API_KEY": API_KEY}
    async with sse_client(SERVER_URL, headers=headers) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])

            result = await session.call_tool(
                "resolve_rwa_asset",
                arguments={"symbol": "PAXG"}
            )
            print(result)

asyncio.run(main())
```

---

## 6. Active MCP toolset

| Tool | Description | Typical arguments |
|---|---|---|
| `resolve_rwa_asset` | Resolve a symbol or token to the canonical parent RWA and `rwa_id` | `symbol` |
| `get_rwa_market_quote` | Fetch quote and token metadata for an RWA asset | `identifier` |
| `compare_rwa_vs_crypto` | Compare a tokenized RWA against crypto by market cap and volume | `rwa_symbol`, `crypto_symbol` |
| `get_rwa_issuers_info` | Return the registered issuer directory and token coverage | `limit`, `start` |
| `get_global_market_metrics` | Return market cap and dominance indicators | none |

### Example resolution behavior

```json
{
  "rwa_id": 1,
  "symbol": "GOLD",
  "resolved_via": "token_symbol",
  "matched_token": {
    "symbol": "PAXG",
    "issuer_id": "issuer-1",
    "issuer_name": "PAX",
    "crypto_id": "gold",
    "rwa_id": 1
  }
}
```

This demonstrates the supported fallback logic: **`PAXG` resolves to parent asset `GOLD`**.

---

## 7. Comparison semantics

When comparing a specific tokenized asset to crypto, the server uses the `is_specific_token` flag.

- **`true`** — specific token such as `PAXG`
- **`false`** — aggregate asset such as `GOLD`

### Comparison formula

$$
\frac{V}{MC} = \frac{\text{24h Volume (USD)}}{\text{Market Capitalization (USD)}}
$$

### Example comparison payload

```json
{
  "comparison_summary": "BTC market cap is 4.72x the size of PAXG (Gold).",
  "rwa_asset": {
    "symbol": "GOLD",
    "name": "Gold",
    "is_specific_token": true,
    "market_cap_usd": 15000000000,
    "volume_24h_usd": 520000000
  },
  "crypto_asset": {
    "symbol": "BTC",
    "name": "Bitcoin",
    "market_cap_usd": 1200000000000,
    "volume_24h_usd": 50000000000,
    "percent_change_24h": 2.5
  }
}
```

---

## 8. Verification steps

### Health check

```bash
curl -i https://cmcserver.fastmcp.app/
```

Expected result:

```text
HTTP/1.1 200 OK
```

### Remote connection check

```bash
npx mcp-remote https://cmcserver.fastmcp.app/mcp --header "X-CMC_PRO_API_KEY:your_coinmarketcap_api_key_here"
```

---

## 9. Troubleshooting

| Issue | Likely cause | Fix |
|---|---|---|
| `mcp-remote: command not found` | Node not installed or `npx` missing | Install Node.js 18+ |
| `401 Unauthorized` | Invalid or missing key | Confirm the `X-CMC_PRO_API_KEY` header and value |
| No tools appear | Remote session not initialized | Restart client and verify the endpoint |
| Server unavailable | Deployment issue | Check `curl -I https://cmcserver.fastmcp.app/` |

---

## 10. Production status

This MCP server is deployed and ready for production connections. Use the endpoint above as the canonical remote target and send the `X-CMC_PRO_API_KEY` header on every tool request.

This is the standard integration pattern for Claude Desktop, Cursor, and custom LangGraph / Python clients.
