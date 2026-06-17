"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os

# Microsoft's enterprise token store client ID. Tokens minted for MCP/API plugins
# in Microsoft 365 Copilot are requested by this first-party application, so its
# app ID appears as the `azp`/`appid` claim in the bearer token.
ENTERPRISE_TOKEN_STORE_CLIENT_ID = "ab3be6b7-f5df-413d-ac2d-abf1e3fd9c0b"


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    """Strongly-typed view over the process environment."""

    def __init__(self) -> None:
        # --- Entra / auth ---
        self.tenant_id = os.getenv("ENTRA_TENANT_ID", "").strip()
        # Accepted token audiences. Set this to the Application ID URI that the
        # Teams Developer Portal generates for your SSO client registration
        # (for example, api://<fqdn>/<client-id>). Multiple values are allowed.
        self.audiences = _split(os.getenv("ENTRA_AUDIENCE", ""))
        # Client applications allowed to call this server. Defaults to the
        # Microsoft enterprise token store. Set to empty to skip the check.
        self.allowed_client_ids = _split(
            os.getenv("ENTRA_ALLOWED_CLIENT_IDS", ENTERPRISE_TOKEN_STORE_CLIENT_ID)
        )
        self.auth_required = os.getenv("AUTH_REQUIRED", "true").strip().lower() == "true"

        # --- PubMed / NCBI E-utilities ---
        self.ncbi_api_key = os.getenv("NCBI_API_KEY", "").strip()
        self.ncbi_tool = os.getenv("NCBI_TOOL", "m365-pubmed-connector").strip()
        self.ncbi_email = os.getenv("NCBI_EMAIL", "").strip()

        # --- Hosting ---
        self.port = int(os.getenv("PORT", "8000"))
        self.mcp_path = os.getenv("MCP_PATH", "/mcp")
        # Hosts/origins permitted by the MCP transport-security (DNS-rebinding)
        # check. Behind Azure Container Apps the public FQDN differs from the
        # container host, so default to allow-all and rely on Entra auth.
        self.allowed_hosts = _split(os.getenv("ALLOWED_HOSTS", "*"))
        self.allowed_origins = _split(os.getenv("ALLOWED_ORIGINS", "*"))

    @property
    def jwks_uri(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"

    @property
    def issuers(self) -> list[str]:
        # Accept both v2.0 and v1.0 issuer formats depending on the app's
        # configured accessTokenAcceptedVersion.
        return [
            f"https://login.microsoftonline.com/{self.tenant_id}/v2.0",
            f"https://sts.windows.net/{self.tenant_id}/",
        ]

    def validate_for_auth(self) -> list[str]:
        """Return a list of misconfiguration messages when auth is enabled."""
        problems: list[str] = []
        if not self.auth_required:
            return problems
        if not self.tenant_id:
            problems.append("ENTRA_TENANT_ID is required when AUTH_REQUIRED=true")
        if not self.audiences:
            problems.append("ENTRA_AUDIENCE is required when AUTH_REQUIRED=true")
        return problems


settings = Settings()
