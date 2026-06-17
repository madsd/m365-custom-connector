"""Microsoft Entra ID bearer-token validation as ASGI middleware.

Implemented as pure ASGI (not BaseHTTPMiddleware) so it never buffers the
streaming MCP responses. Requests without a valid token are rejected with a
401 before they reach the MCP application.
"""
from __future__ import annotations

import json
import logging

import jwt
from jwt import PyJWKClient

from .config import settings

logger = logging.getLogger("pubmed_connector.auth")

_UNPROTECTED_PATHS = {"/health"}


class AuthMiddleware:
    def __init__(self, app) -> None:
        self.app = app
        self._jwk_client: PyJWKClient | None = None
        if settings.auth_required:
            self._jwk_client = PyJWKClient(settings.jwks_uri)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.auth_required:
            return await self.app(scope, receive, send)

        if scope.get("path", "") in _UNPROTECTED_PATHS:
            return await self.app(scope, receive, send)

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        authorization = headers.get("authorization", "")
        error = self._validate(authorization)
        if error:
            return await self._reject(send, error)

        return await self.app(scope, receive, send)

    def _validate(self, authorization: str) -> str | None:
        if not authorization.lower().startswith("bearer "):
            return "Missing or malformed Authorization header"
        token = authorization[7:].strip()

        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)  # type: ignore[union-attr]
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.audiences,
                options={"require": ["exp", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            logger.warning("Token rejected: %s", exc)
            return f"Invalid token: {exc}"

        if claims.get("iss") not in settings.issuers:
            return "Token issuer is not trusted"

        if settings.allowed_client_ids:
            client_id = claims.get("azp") or claims.get("appid")
            if client_id not in settings.allowed_client_ids:
                return "Calling client application is not allowed"

        return None

    @staticmethod
    async def _reject(send, message: str):
        body = json.dumps({"error": "unauthorized", "message": message}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer error="invalid_token"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
