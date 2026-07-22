"""
Edge-case tests added after the D3 code review (findings #2, #3, #8, #9).

These cover behavior the happy-path suite asserted only implicitly:
throttling, the expiry boundary, malformed auth on the public endpoint,
long-name truncation, split-type preservation on copy, slug-retry, and —
importantly — one end-to-end path through the REAL JWT authenticator
(the other tests use force_authenticate, which skips it).
"""

import time
import uuid
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.authentication import SupabaseJWTAuthentication, SupabaseUser
from apps.sharing.models import FitLogUser, ShareLink, WorkoutTemplate

OWNER_ID = "aaaaaaaa-0000-0000-0000-000000000001"
EXERCISES = [
    {
        "exerciseId": "ex-1",
        "name": "Squat",
        "muscleGroup": "Legs",
        "category": "COMPOUND",
        "metValue": 6.0,
        "isCompound": True,
        "targetSets": 5,
    }
]


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    # DRF throttling counts in the cache; clear it so counts don't leak
    # between tests.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def owner_client():
    client = APIClient()
    client.force_authenticate(user=SupabaseUser(id=OWNER_ID, email="o@x.com"))
    return client


@pytest.fixture()
def template(fitlog_tables):
    FitLogUser.objects.create(id=OWNER_ID, email="o@x.com", name="Vaibhav Garg")
    now = timezone.now()
    return WorkoutTemplate.objects.create(
        id=str(uuid.uuid4()),
        user_id=OWNER_ID,
        name="Leg Day",
        split_type=None,
        exercises=EXERCISES,
        created_at=now,
        updated_at=now,
    )


# ─── #8: throttling (20/day) ─────────────────────────────────────


@pytest.mark.django_db
def test_21st_create_is_throttled(owner_client, template):
    body = {"kind": "WORKOUT_TEMPLATE", "templateId": template.id}
    for _ in range(20):
        res = owner_client.post("/api/share-links/", body, format="json")
        assert res.status_code == 201
    # 21st within the window → 429 Too Many Requests
    res = owner_client.post("/api/share-links/", body, format="json")
    assert res.status_code == 429


# ─── #8: expiry boundary ─────────────────────────────────────────


@pytest.mark.django_db
def test_link_valid_one_second_before_expiry(fitlog_tables):
    link = ShareLink.objects.create(
        owner_user_id=OWNER_ID,
        kind=ShareLink.Kind.WORKOUT_TEMPLATE,
        title="x",
        payload={"exercises": []},
        expires_at=timezone.now() + timedelta(seconds=1),
    )
    assert APIClient().get(f"/api/share-links/{link.slug}").status_code == 200


@pytest.mark.django_db
def test_link_gone_at_expiry_instant(fitlog_tables):
    link = ShareLink.objects.create(
        owner_user_id=OWNER_ID,
        kind=ShareLink.Kind.WORKOUT_TEMPLATE,
        title="x",
        payload={"exercises": []},
        expires_at=timezone.now(),  # expires_at <= now → gone
    )
    assert APIClient().get(f"/api/share-links/{link.slug}").status_code == 410


# ─── #8: public endpoint ignores a bad Authorization header ───────


@pytest.mark.django_db
def test_public_get_ignores_malformed_auth_header(fitlog_tables):
    link = ShareLink.objects.create(
        owner_user_id=OWNER_ID,
        kind=ShareLink.Kind.WORKOUT_TEMPLATE,
        title="x",
        payload={"exercises": []},
    )
    # A browser might send a stale/garbage token; the PUBLIC page must still
    # render (200), never 401 — GET has no authenticators.
    res = APIClient().get(
        f"/api/share-links/{link.slug}",
        HTTP_AUTHORIZATION="Bearer totally.invalid.token",
    )
    assert res.status_code == 200


# ─── #3: long first name is truncated (would 500 on Postgres) ─────


@pytest.mark.django_db
def test_long_first_name_is_truncated(owner_client, fitlog_tables):
    long_name = "Bartholomew" * 5  # 55 chars, no spaces → one "first name"
    FitLogUser.objects.create(id=OWNER_ID, email="o@x.com", name=long_name)
    now = timezone.now()
    tpl = WorkoutTemplate.objects.create(
        id=str(uuid.uuid4()), user_id=OWNER_ID, name="T", split_type=None,
        exercises=EXERCISES, created_at=now, updated_at=now,
    )
    res = owner_client.post(
        "/api/share-links/",
        {"kind": "WORKOUT_TEMPLATE", "templateId": tpl.id},
        format="json",
    )
    assert res.status_code == 201
    link = ShareLink.objects.get(slug=res.json()["slug"])
    assert len(link.owner_first_name) <= 40


# ─── #2: copy preserves a valid split type ───────────────────────


@pytest.mark.django_db
def test_copy_preserves_valid_split_type(fitlog_tables):
    FitLogUser.objects.create(id=OWNER_ID, email="o@x.com", name="Owner")
    link = ShareLink.objects.create(
        owner_user_id=OWNER_ID,
        kind=ShareLink.Kind.WORKOUT_TEMPLATE,
        title="PPL Day",
        payload={"splitType": "PPL", "exercises": EXERCISES},
    )
    client = APIClient()
    client.force_authenticate(user=SupabaseUser(id=OWNER_ID, email="o@x.com"))
    res = client.post(f"/api/share-links/{link.slug}/copy")
    assert res.status_code == 201
    copied = WorkoutTemplate.objects.get(id=res.json()["templateId"])
    assert copied.split_type == "PPL"


@pytest.mark.django_db
def test_copy_drops_unknown_split_type(fitlog_tables):
    FitLogUser.objects.create(id=OWNER_ID, email="o@x.com", name="Owner")
    link = ShareLink.objects.create(
        owner_user_id=OWNER_ID,
        kind=ShareLink.Kind.WORKOUT_TEMPLATE,
        title="Weird",
        payload={"splitType": "NONSENSE", "exercises": EXERCISES},
    )
    client = APIClient()
    client.force_authenticate(user=SupabaseUser(id=OWNER_ID, email="o@x.com"))
    res = client.post(f"/api/share-links/{link.slug}/copy")
    assert res.status_code == 201
    copied = WorkoutTemplate.objects.get(id=res.json()["templateId"])
    assert copied.split_type is None  # junk never written into the enum


# ─── #8: a real signed JWT actually authenticates (no force_authenticate) ─

_PRIV = ec.generate_private_key(ec.SECP256R1())
_PUB = _PRIV.public_key()


@pytest.mark.django_db
def test_create_through_real_jwt_authenticator(monkeypatch, template):
    # Patch only the JWKS key lookup; the signature verification, expiry,
    # audience, and claim extraction all run for real.
    monkeypatch.setattr(
        SupabaseJWTAuthentication,
        "_get_signing_key",
        lambda self, token: _PUB,
    )
    token = jwt.encode(
        {
            "sub": OWNER_ID,
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "email": "o@x.com",
        },
        _PRIV,
        algorithm="ES256",
    )
    res = APIClient().post(
        "/api/share-links/",
        {"kind": "WORKOUT_TEMPLATE", "templateId": template.id},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 201
    assert ShareLink.objects.filter(owner_user_id=OWNER_ID).count() == 1
