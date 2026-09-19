# FastMCP Server Deployment & Production Setup Guide

This document outlines the full deployment procedure for the CoinMarketCap Real-World Asset (RWA) & Crypto Intelligence FastMCP server. It covers local setup, environment configuration, Docker deployment, production hosting, and health verification.

## 1. Overview

The service is a stateless FastMCP HTTP server that exposes live CoinMarketCap market tools to MCP-compatible clients over HTTP/SSE-compatible transport. Each client request authenticates with a per-request `X-CMC_PRO_API_KEY` header, so the server can safely serve multiple users or multiple agent sessions without sharing a single global secret.

Production endpoint:

- MCP endpoint: `https://cmcserver.fastmcp.app/mcp`
- Health route: `https://cmcserver.fastmcp.app/`

The server exposes tools such as:

- `resolve_rwa_asset`
- `get_rwa_market_quote`
- `compare_rwa_vs_crypto`
- `get_rwa_issuers_info`
- `get_global_market_metrics`

---

## 2. System Architecture

```text
┌─────────────────────────┐      HTTP / SSE       ┌────────────────────────────┐
│                         │ ───────────────────> │ FastMCP Server             │
│ AI Client / Agent       │                       │ (Uvicorn / HTTP transport) │
│                         │ <─────────────────── │                            │
└─────────────────────────┘                       └──────────────┬─────────────┘
                                                              │
                                                              │ X-CMC_PRO_API_KEY
                                                              ▼
                                                   ┌─────────────────────────┐
                                                   │ CoinMarketCap Pro API   │
                                                   └─────────────────────────┘
```

### Requirements

- Python 3.10 or 3.11
- Port availability on `8080` or a custom `PORT` value
- CoinMarketCap Pro API key
- Dependencies from `requirements.txt`

Core Python requirements:

- `fastmcp>=2.0.0`
- `mcp>=2.0.0`
- `httpx>=0.27.0`
- `pydantic>=2.6.0`
- `pydantic-settings>=2.2.0`
- `python-dotenv>=1.0.12`

---

## 3. Environment Configuration

Create a `.env` file from the example file in the project root.

```bash
cp .env.example .env
```

Example environment file:

```ini
# Required: CoinMarketCap API key
CMC_API_KEY=your_coinmarketcap_api_key_here

# Optional for local AI eval/test workflows
OPENAI_API_KEY=your_openai_api_key_here
MODEL_BASE_URL=https://api.openai.com/v1

# CoinMarketCap API settings
CMC_BASE_URL=https://pro-api.coinmarketcap.com
CMC_TIMEOUT_SECONDS=10.0
CMC_RATE_LIMIT_PER_MINUTE=30
CMC_MAX_RETRIES=3
CMC_RETRY_BACKOFF_BASE_SECONDS=1.0

# Server binding settings
PORT=8080
HOST=0.0.0.0
```

### Important notes

- `CMC_API_KEY` is mandatory for live tool calls.
- `PORT` controls the exposed local or container HTTP port.
- `HOST=0.0.0.0` makes the service reachable from container or cloud deployment environments.

---

## 4. Local Development Setup

### Step 1: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Start the FastMCP server

```bash
python -m app.server
```

### Expected startup output

```text
Starting user MCP on port 8080...
INFO     Starting MCP server 'CMC Real-World Asset Intelligence' with transport 'http' (stateless) on http://0.0.0.0:8080/mcp
INFO:    Started server process [5]
INFO:    Waiting for application startup.
INFO:    Application startup complete.
INFO:    Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

The server should serve MCP traffic on:

```text
http://127.0.0.1:8080/mcp
```

When deployed publicly, the same endpoint is exposed through the production URL.

---

## 5. Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8080

CMD ["python", "-m", "app.server"]
```

### Build image

```bash
docker build -t cmc-rwa-mcp:latest .
```

### Run container

```bash
docker run -d \
  --name cmc-mcp-server \
  -p 8080:8080 \
  --env-file .env \
  cmc-rwa-mcp:latest
```

This container starts the same FastMCP server with the same environment variables and tool set.

---

## 6. Production Hosting Options

### Option A: FastMCP Cloud / Prefect Horizon

Deploy directly using the FastMCP CLI:

```bash
fastmcp deploy app/server.py:mcp --name "cmc-rwa-intelligence"
```

This is the cleanest path when deploying a FastMCP-native service with remote MCP access.

### Option B: Railway / Render / Fly.io / Similar PaaS

1. Push the repository to GitHub.
2. Connect the repo to your hosting platform.
3. Set build command:

```bash
pip install -r requirements.txt
```

4. Set start command:

```bash
python -m app.server
```

5. Add environment variable:

```bash
CMC_API_KEY=your_coinmarketcap_api_key_here
```

6. Ensure the service health endpoint points to:

```text
GET /
```

7. Confirm the app exposes port `8080` or the provider's configured `PORT` value.

---

## 7. Production Health Checks

### Check root endpoint

```bash
curl -i https://cmcserver.fastmcp.app/
```

Expected response:

```text
HTTP/1.1 200 OK
```

This confirms the service is alive and reachable.

### Verify MCP endpoint

```bash
curl -I https://cmcserver.fastmcp.app/mcp
```

You should receive an HTTP success response from the deployed MCP endpoint.

---

## 8. Security Notes

- Never hardcode API keys in the repository.
- Use environment variables or secret stores in production.
- Validate that the upstream `X-CMC_PRO_API_KEY` header matches the target API key exactly.
- Restrict access to deployment endpoints using platform-level auth if needed.

---

## 9. Production Deployment Summary

This project is designed for a production-ready MCP deployment pattern:

- a lightweight FastMCP server,
- stateless request handling,
- per-request API-key authentication,
- live CoinMarketCap integration,
- remote HTTP connectivity for AI agents and clients.

The live production service is already available at:

```text
https://cmcserver.fastmcp.app/mcp
```

For remote AI clients, connect using the `X-CMC_PRO_API_KEY` header with your CoinMarketCap Pro key.

---

## 10. Recommended Deployment Checklist

Before production rollout, confirm the following:

- [ ] `CMC_API_KEY` is set in the deployment environment
- [ ] `PORT` is configured correctly for the hosting platform
- [ ] Health route `/` returns `200 OK`
- [ ] MCP endpoint `/mcp` is reachable
- [ ] Authentication header `X-CMC_PRO_API_KEY` is passed on every client request
- [ ] Logs are clean and no secrets are printed to stdout

This is the stable deployment path for the live market intelligence MCP server.
