# FastMCP Server Deployment & Production Setup Guide

This document defines the production deployment path for the CoinMarketCap Real-World Asset (RWA) & Crypto Intelligence FastMCP server.

## 1. Overview

The service is a stateless FastMCP HTTP server that exposes CoinMarketCap-backed intelligence to MCP clients over remote HTTP/SSE transport. Each request is authenticated via the `X-CMC_PRO_API_KEY` header, which ensures per-request authorization without hardcoding a global key into the runtime environment.

### Production endpoints

- **Remote MCP endpoint:** `https://cmcserver.fastmcp.app/mcp`
- **Health route:** `https://cmcserver.fastmcp.app/`

### Live tool capabilities

- `resolve_rwa_asset`
- `get_rwa_market_quote`
- `compare_rwa_vs_crypto`
- `get_rwa_issuers_info`
- `get_global_market_metrics`

---

## 2. Runtime and platform requirements

- **Python:** 3.10 or 3.11
- **Port:** `8080` or a platform-provided `PORT`
- **API key:** valid CoinMarketCap Pro credential
- **Dependencies:** from `requirements.txt`

### Core packages

- `fastmcp>=2.0.0`
- `mcp>=2.0.0`
- `httpx>=0.27.0`
- `pydantic>=2.6.0`
- `pydantic-settings>=2.2.0`
- `python-dotenv>=1.0.12`

---

## 3. Environment configuration

Create the deployment environment file at the project root:

```bash
cp .env.example .env
```

Example `.env`:

```ini
CMC_API_KEY=your_coinmarketcap_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
MODEL_BASE_URL=https://api.openai.com/v1

CMC_BASE_URL=https://pro-api.coinmarketcap.com
CMC_TIMEOUT_SECONDS=10.0
CMC_RATE_LIMIT_PER_MINUTE=30
CMC_MAX_RETRIES=3
CMC_RETRY_BACKOFF_BASE_SECONDS=1.0

PORT=8080
HOST=0.0.0.0
```

### Required settings

- **`CMC_API_KEY`** — required for all live market calls
- **`PORT`** — required for deployment platforms
- **`HOST`** — should be `0.0.0.0` for containerized deployment

---

## 4. Local run instructions

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start the server

```bash
python -m app.server
```

### Expected startup output

```text
INFO     Starting MCP server 'CMC Real-World Asset Intelligence' with transport 'http' (stateless) on http://0.0.0.0:8080/mcp
INFO:    Started server process [5]
INFO:    Waiting for application startup.
INFO:    Application startup complete.
INFO:    Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

The local endpoint is:

```text
http://127.0.0.1:8080/mcp
```

---

## 5. Docker deployment

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

### Build and run

```bash
docker build -t cmc-rwa-mcp:latest .
docker run -d \
  --name cmc-mcp-server \
  -p 8080:8080 \
  --env-file .env \
  cmc-rwa-mcp:latest
```

---

## 6. Production hosting options

### Option A — FastMCP Cloud / Prefect Horizon

```bash
fastmcp deploy app/server.py:mcp --name "cmc-rwa-intelligence"
```

### Option B — Railway / Render / Fly.io / any PaaS

1. Connect the GitHub repo to the hosting platform.
2. Set the build command:

```bash
pip install -r requirements.txt
```

3. Set the start command:

```bash
python -m app.server
```

4. Configure environment variable:

```bash
CMC_API_KEY=your_coinmarketcap_api_key_here
```

5. Ensure the root health endpoint is exposed and reachable over `GET /`.

---

## 7. Health checks and validation

### Root health check

```bash
curl -i https://cmcserver.fastmcp.app/
```

Expected result:

```text
HTTP/1.1 200 OK
```

### MCP endpoint validation

```bash
curl -I https://cmcserver.fastmcp.app/mcp
```

---

## 8. Operational notes

### Resolution fallback behavior

The server supports a two-step asset lookup path:

1. direct symbol lookup
2. issuer token scan and parent `rwa_id` mapping

This is the reason a token such as `PAXG` can resolve back to parent asset `GOLD` with `rwa_id = 1`.

### Comparison semantics

The comparison engine records whether the RWA object is a specific token or an aggregate market asset by setting the `is_specific_token` flag.

### Compliance and attestation awareness

Issuer metadata is surfaced in a way that supports institutional evaluation, including reserve attestation, custody structure, and regulatory context.

---

## 9. Recommended deployment checklist

- [ ] `CMC_API_KEY` set in deployment environment
- [ ] `PORT` configured correctly
- [ ] `/` returns `200 OK`
- [ ] `/mcp` is reachable
- [ ] `X-CMC_PRO_API_KEY` passed by each client
- [ ] Logs do not expose sensitive data

This is the stable production deployment pattern for the live market intelligence MCP server.
