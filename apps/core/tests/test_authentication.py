"""
SupabaseJWTAuthentication tests — the cross-service trust boundary.

Strategy: generate a real ES256 keypair (the algorithm Supabase's new
signing keys use), sign tokens with it, and monkeypatch the JWKS lookup
to return our public key. No network, no Supabase — pure signature math,
exactly what production does after the JWKS cache is warm.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from apps.core.authentication import SupabaseJWTAuthentication

# ── Test keys ────────────────────────────────────────────────────
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
PUBLIC_KEY = PRIVATE_KEY.public_key()

ATTACKER_KEY = ec.generate_private_key(ec.SECP256R1())

USER_ID = "11111111-2222-3333-4444-555555555555"


def make_token(
    *,
    key=PRIVATE_KEY,
    sub: str = USER_ID,
    aud: str = "authenticated",
    exp_offset: int = 3600,
    **extra,
) -> str:
    claims = {
        "sub": sub,
        "aud": aud,
        "exp": int(time.time()) + exp_offset,
        "email": "test@example.com",
        **extra,
    }
    return jwt.encode(claims, key, algorithm="ES256")


@pytest.fixture()
def auth(monkeypatch):
    """Authentication instance whose JWKS lookup returns OUR public key."""
    instance = SupabaseJWTAuthentication()
    monkeypatch.setattr(
        SupabaseJWTAuthentication,
        "_get_signing_key",
        lambda self, token: PUBLIC_KEY,
    )
    return instance


def make_request(token: str | None):
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    if token is None:
        return factory.get("/api/whoami")
    return factory.get("/api/whoami", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_valid_token_yields_user(auth):
    user, _ = auth.authenticate(make_request(make_token()))
    assert user.id == USER_ID
    assert user.email == "test@example.com"
    assert user.is_authenticated is True


def test_missing_header_returns_none(auth):
    # None = "no credentials" → DRF permissions produce the 401.
    assert auth.authenticate(make_request(None)) is None


def test_expired_token_rejected(auth):
    from rest_framework.exceptions import AuthenticationFailed

    with pytest.raises(AuthenticationFailed, match="expired"):
        auth.authenticate(make_request(make_token(exp_offset=-60)))


def test_tampered_signature_rejected(auth):
    """Token signed by a DIFFERENT key must fail — the core guarantee."""
    from rest_framework.exceptions import AuthenticationFailed

    forged = make_token(key=ATTACKER_KEY)
    with pytest.raises(AuthenticationFailed, match="Invalid token"):
        auth.authenticate(make_request(forged))


def test_wrong_audience_rejected(auth):
    from rest_framework.exceptions import AuthenticationFailed

    with pytest.raises(AuthenticationFailed, match="Invalid token"):
        auth.authenticate(make_request(make_token(aud="something-else")))


def test_garbage_token_rejected(auth):
    from rest_framework.exceptions import AuthenticationFailed

    with pytest.raises(AuthenticationFailed, match="Invalid token"):
        auth.authenticate(make_request("not.a.jwt"))


def test_malformed_header_rejected(auth):
    from rest_framework.exceptions import AuthenticationFailed
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().get(
        "/api/whoami", HTTP_AUTHORIZATION="Token abc def"
    )
    with pytest.raises(AuthenticationFailed):
        auth.authenticate(request)


def test_whoami_endpoint_requires_auth(client):
    """End-to-end through the URL layer: no token → 401, never 200."""
    response = client.get("/api/whoami")
    assert response.status_code == 401
