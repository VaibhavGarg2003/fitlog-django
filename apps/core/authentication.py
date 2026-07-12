"""
Supabase JWT Authentication for DRF
════════════════════════════════════

ONE identity provider, TWO verifiers.

The Next.js app and this Django service trust the same Supabase Auth.
A request arrives with `Authorization: Bearer <jwt>` — the SAME token the
browser already holds from its Supabase session. We verify the signature
against Supabase's public JWKS (asymmetric keys, ES256/RS256), check
expiry + audience, and extract the user id (`sub` claim). That id is the
same uuid as the `users` table, so Django rows join cleanly.

No passwords in Django. No second login. No session sync.

This is the DRF-native version of what lib/supabase/server.ts's
getClaims() does in Next.js: local signature verification, with the
public keyset fetched once and cached (PyJWKClient caches internally).
"""

from dataclasses import dataclass, field
from typing import Any

import jwt
from django.conf import settings
from jwt import PyJWKClient
from rest_framework import authentication, exceptions

# Module-level client so the JWKS fetch is cached across requests —
# a long-running server can do this (serverless couldn't).
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.SUPABASE_JWKS_URL:
            raise exceptions.AuthenticationFailed(
                "Supabase is not configured on this server."
            )
        _jwks_client = PyJWKClient(settings.SUPABASE_JWKS_URL, cache_keys=True)
    return _jwks_client


@dataclass
class SupabaseUser:
    """
    A minimal stand-in for Django's User — we deliberately do NOT create
    django.contrib.auth rows for Supabase users. Identity lives in
    Supabase; this object just carries the verified claims through the
    request. DRF's IsAuthenticated only needs `.is_authenticated`.
    """

    id: str
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"SupabaseUser({self.id})"


class SupabaseJWTAuthentication(authentication.BaseAuthentication):
    """DRF authentication class: verify a Supabase-issued JWT locally."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header:
            return None  # no credentials → let permissions decide (401)

        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise exceptions.AuthenticationFailed(
                "Authorization header must be: Bearer <token>."
            )
        token = parts[1]

        try:
            signing_key = self._get_signing_key(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256"],
                audience=settings.SUPABASE_JWT_AUDIENCE,
                options={"require": ["exp", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise exceptions.AuthenticationFailed("Token has expired.") from exc
        except jwt.PyJWTError as exc:
            # Covers bad signature, wrong audience, malformed token, and
            # JWKS lookup failures. One generic message — never explain to
            # an attacker WHICH check failed.
            raise exceptions.AuthenticationFailed("Invalid token.") from exc

        user = SupabaseUser(
            id=claims["sub"],
            email=claims.get("email"),
            claims=claims,
        )
        return (user, token)

    def _get_signing_key(self, token: str):
        """Separated for testability — tests inject a known key here."""
        return _get_jwks_client().get_signing_key_from_jwt(token).key

    def authenticate_header(self, request):
        # Tells DRF to answer 401 (not 403) when credentials are absent.
        return self.keyword
