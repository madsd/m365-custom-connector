# PubMed custom federated connector for Microsoft 365 Copilot

A Model Context Protocol (MCP) server that brings the public [PubMed](https://pubmed.ncbi.nlm.nih.gov/)
biomedical literature database into **Microsoft 365 Copilot** as a
[custom federated connector](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/set-up-custom-federated-connectors).

Users can ask Copilot natural-language questions ("find recent trials on CRISPR for sickle
cell disease") and Copilot calls this server in real time to search and read PubMed articles.

## What's in the box

| Path | Purpose |
| --- | --- |
| `src/server.py` | MCP server exposing the read-only `search` and `fetch` tools |
| `src/pubmed.py` | Async client for the NCBI E-utilities API (with rate-limit handling) |
| `src/auth.py` | Microsoft Entra ID bearer-token validation (ASGI middleware) |
| `src/config.py` | Environment-driven configuration |
| `src/main.py` | ASGI entrypoint (Uvicorn) |
| `Dockerfile` | Container image |
| `azure.yaml`, `infra/` | `azd` + Bicep for Azure Container Apps |
| `scripts/smoke_test.py` | End-to-end MCP client test |
| `docs/tenant-setup-guide.md` | **Step-by-step tenant configuration + validation guide** |

## Architecture

```
Microsoft 365 Copilot
   │  (1) user prompt
   ▼
Copilot orchestrator ──(2) bearer token from Microsoft enterprise token store──┐
   │                                                                            │
   │  (3) MCP search / fetch over HTTPS                                         │
   ▼                                                                            │
Azure Container Apps  ──(4) validate Entra JWT (issuer, audience, client app)──┘
   │
   │  (5) NCBI E-utilities (esearch / esummary / efetch)
   ▼
PubMed (public)
```

## MCP tools

- **`search(query, max_results)`** → `{ "results": [ { id, title, url, snippet } ] }`
  where `id` is the PubMed PMID.
- **`fetch(id)`** → `{ id, title, text, url, metadata }` where `text` is the article
  abstract and `metadata` includes journal, authors, publication date, and DOI.

Both tools are **read-only**.

## Quick start (local)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run without auth for local testing
$env:AUTH_REQUIRED = "false"
$env:NCBI_EMAIL    = "you@example.com"   # recommended by NCBI
python -m src.main

# In another terminal: end-to-end test
python scripts\smoke_test.py
```

Then point [MCP Inspector](https://github.com/modelcontextprotocol/inspector) at
`http://localhost:8000/mcp` (transport: *Streamable HTTP*) to explore the tools interactively:

```powershell
npx @modelcontextprotocol/inspector
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Required | Description |
| --- | --- | --- |
| `AUTH_REQUIRED` | no (default `true`) | Enforce Entra bearer-token validation. |
| `ENTRA_TENANT_ID` | when auth on | Your Microsoft Entra tenant ID. |
| `ENTRA_AUDIENCE` | when auth on | Accepted token audience = the Application ID URI from the Teams Developer Portal SSO registration. Comma-separated list allowed. |
| `ENTRA_ALLOWED_CLIENT_IDS` | no | Allowed calling client app IDs. Defaults to the Microsoft enterprise token store `ab3be6b7-f5df-413d-ac2d-abf1e3fd9c0b`. |
| `NCBI_API_KEY` | no | NCBI API key for higher PubMed rate limits (10/sec vs 3/sec). |
| `NCBI_EMAIL` | no | Contact email reported to NCBI (recommended). |
| `MCP_PATH` | no (default `/mcp`) | Path of the MCP streamable-HTTP endpoint. |
| `ALLOWED_HOSTS` | no (default `*`) | Hosts allowed by the MCP transport-security (DNS-rebinding) check. `*` disables the check (recommended behind Azure ingress, where Entra auth still applies). Set explicit hostnames to enable strict checking. |
| `ALLOWED_ORIGINS` | no (default `*`) | Origins allowed by the DNS-rebinding check. |
| `PORT` | no (default `8000`) | Listen port. |

## Deploy to Azure

```powershell
azd auth login
azd env new pubmed-connector
azd env set AUTH_REQUIRED false   # first deploy: get the URL, then lock down
azd up
```

Full deployment, Entra SSO setup, M365 admin center registration, and validation steps are in
**[docs/tenant-setup-guide.md](docs/tenant-setup-guide.md)**.

## Security notes

- The connector exposes only public PubMed data, but the **transport is still
  authenticated**: every `/mcp` request must carry a valid Entra token whose audience matches
  your Application ID URI and whose calling app is the Microsoft enterprise token store.
- `/health` is intentionally unauthenticated for container liveness probes.
- The server is read-only and performs no writes to any system.
