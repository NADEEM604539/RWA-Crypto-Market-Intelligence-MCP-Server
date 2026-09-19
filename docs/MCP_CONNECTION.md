# Remote MCP Server Connection Guide

This guide explains how to connect AI clients and local developer tools to the deployed CoinMarketCap RWA & Crypto Intelligence FastMCP server.

## 1. Deployed Server Details

The server is live and deployed at:

- MCP Endpoint: `https://cmcserver.fastmcp.app/mcp`
- Transport: HTTP / Server-Sent Events (SSE) via MCP remote transport
- Authentication Header: `X-CMC_PRO_API_KEY`

This is the main public entry point for all MCP clients.

---

## 2. Authentication Model

The server authenticates every incoming request using the `X-CMC_PRO_API_KEY` header. The value must match a valid CoinMarketCap Pro API key.

Example:

```http
X-CMC_PRO_API_KEY: your_coinmarketcap_api_key_here
```

> Never commit real keys into version-controlled files. Store them in `.env`, a secret manager, or your client environment variables.

---

## 3. Claude Desktop Connection

Claude Desktop typically runs local stdio tools, so the remote HTTPS endpoint is bridged through `mcp-remote`.

### Configuration path

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

If `npx` is not on the PATH, use the full Node binary path.

```json
{
  "command": "D:\\node-v20.19.1-win-x64\\node-v20.19.1-win-x64\\npx.cmd"
}
```

After saving the config, fully quit Claude Desktop and reopen it.

---

## 4. Cursor IDE Connection

1. Open Cursor settings.
2. Navigate to Features -> MCP Servers.
3. Click Add New MCP Server.
4. Fill in the fields as shown below:

- Name: `coinmarketcap`
- Type: `command`
- Command:

```bash
npx mcp-remote https://cmcserver.fastmcp.app/mcp --header "X-CMC_PRO_API_KEY:your_coinmarketcap_api_key_here"
```

This lets Cursor connect to the deployed service without needing a local stdio server.

---

## 5. Python Client Connection Example

This example uses the MCP Python client and connects over HTTP/SSE transport.

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
            print("Connected tools:", [t.name for t in tools.tools])

            result = await session.call_tool(
                "get_rwa_market_quote",
                arguments={"identifier": "GOLD"}
            )
            print(result.content)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Registered Tools

Once connected, the server exposes the following tools:

| Tool Name | Description | Typical Parameters |
|---|---|---|
| `resolve_rwa_asset` | Resolves a symbol like `PAXG` to its canonical RWA record | `symbol` |
| `get_rwa_market_quote` | Fetches live price, market cap, volume, and token metadata | `identifier` |
| `compare_rwa_vs_crypto` | Compares an RWA to a cryptocurrency | `rwa_symbol`, `crypto_symbol` |
| `get_rwa_issuers_info` | Lists registered RWA issuers and token counts | `limit` |
| `get_global_market_metrics` | Retrieves crypto macro metrics like BTC dominance | none |

---

## 7. Connection Verification

### Health check

```bash
curl -i https://cmcserver.fastmcp.app/
```

Expected result:

```text
HTTP/1.1 200 OK
```

### Manual remote MCP verification

```bash
npx mcp-remote https://cmcserver.fastmcp.app/mcp --header "X-CMC_PRO_API_KEY:your_coinmarketcap_api_key_here"
```

This should open the remote MCP session and confirm the header is accepted.

---

## 8. Troubleshooting

### `mcp-remote: command not found`

Install Node.js 18+ and ensure `npx` is in your PATH.

### `401 Unauthorized`

Check that:

- the API key is valid,
- the header name is exactly `X-CMC_PRO_API_KEY`,
- there are no extra spaces or trailing characters in the value.

### Claude Desktop not showing the tool list

- Exit Claude Desktop completely
- Ensure no background Claude process remains active
- Reopen the app and reload the config

### Server appears unavailable

Check the public health endpoint:

```bash
curl -I https://cmcserver.fastmcp.app/
```

If the health endpoint is not returning `200 OK`, the service or platform deployment needs attention.

---

## 9. Recommended Client Setup Pattern

For any AI agent or language model client, use this pattern:

```text
Remote MCP URL: https://cmcserver.fastmcp.app/mcp
Authentication: X-CMC_PRO_API_KEY: <your_valid_cmc_key>
Transport: HTTP / SSE
```

This is the supported integration pattern for remote deployments of this project.

---

## 10. Production Status

The server is deployed and ready for MCP client connectivity. Use the public endpoint above as the canonical remote server target and pass the `X-CMC_PRO_API_KEY` header on each request.

This setup is production-ready for Claude Desktop, Cursor, custom LangGraph agents, and other MCP-compatible clients.
