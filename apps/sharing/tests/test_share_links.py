"""
Share-links API tests — every hidden requirement from doc 06 gets a test:
snapshot semantics, ownership (404 not 403), revoke, expiry (410),
public access, unguessable slugs, and the copy flow.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.authentication import SupabaseUser
from apps.sharing.models import FitLogUser, ShareLink, WorkoutTemplate

OWNER_ID = "aaaaaaaa-0000-0000-0000-000000000001"
FRIEND_ID = "bbbbbbbb-0000-0000-0000-000000000002"

EXERCISES = [
    {
        "exerciseId": "ex-1",
        "name": "Bench Press",
        "muscleGroup": "Chest",
        "category": "COMPOUND",
        "metValue": 6.0,
        "isCompound": True,
        "targetSets": 4,
    }
]


@pytest.fixture()
def owner_client():
    client = APIClient()
    client.force_authenticate(user=SupabaseUser(id=OWNER_ID, email="o@x.com"))
    return client


@pytest.fixture()
def friend_client():
    client = APIClient()
    client.force_authenticate(user=SupabaseUser(id=FRIEND_ID, email="f@x.com"))
    return client


@pytest.fixture()
def template(fitlog_tables):
    FitLogUser.objects.create(id=OWNER_ID, email="o@x.com", name="Vaibhav Garg")
    FitLogUser.objects.create(id=FRIEND_ID, email="f@x.com", name="Friend Person")
    now = timezone.now()
    return WorkoutTemplate.objects.create(
        id=str(uuid.uuid4()),
        user_id=OWNER_ID,
        name="Push Day A",
        split_type=None,
        exercises=EXERCISES,
        created_at=now,
        updated_at=now,
    )


def make_link(**overrides) -> ShareLink:
    defaults = dict(
        owner_user_id=OWNER_ID,
        owner_first_name="Vaibhav",
        kind=ShareLink.Kind.WORKOUT_TEMPLATE,
        title="Push Day A",
        payload={
            "templateName": "Push Day A",
            "splitType": None,
            "exercises": EXERCISES,
        },
        expires_at=timezone.now() + timedelta(days=90),
    )
    defaults.update(overrides)
    return ShareLink.objects.create(**defaults)


# ─── Create ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_snapshots_the_template(owner_client, template):
    res = owner_client.post(
        "/api/share-links/",
        {"kind": "WORKOUT_TEMPLATE", "templateId": template.id},
        format="json",
    )
    assert res.status_code == 201
    link = ShareLink.objects.get(slug=res.json()["slug"])
    assert link.payload["exercises"] == EXERCISES
    assert link.owner_first_name == "Vaibhav"  # first name ONLY
    assert link.expires_at is not None  # default expiry applied

    # THE SNAPSHOT GUARANTEE: editing the template later must not change
    # what the link shows.
    template.exercises = []
    template.save()
    link.refresh_from_db()
    assert link.payload["exercises"] == EXERCISES


@pytest.mark.django_db
def test_cannot_share_someone_elses_template(friend_client, template):
    res = friend_client.post(
        "/api/share-links/",
        {"kind": "WORKOUT_TEMPLATE", "templateId": template.id},
        format="json",
    )
    assert res.status_code == 404  # not 403 — never reveal existence


@pytest.mark.django_db
def test_slugs_are_unguessable(owner_client, template):
    slugs = set()
    for _ in range(3):
        res = owner_client.post(
            "/api/share-links/",
            {"kind": "WORKOUT_TEMPLATE", "templateId": template.id},
            format="json",
        )
        slugs.add(res.json()["slug"])
    assert len(slugs) == 3
    assert all(len(s) >= 10 for s in slugs)


# ─── Public view ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_public_get_needs_no_auth_and_counts_views(fitlog_tables):
    link = make_link()
    anonymous = APIClient()

    res = anonymous.get(f"/api/share-links/{link.slug}")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Push Day A"
    assert body["ownerFirstName"] == "Vaibhav"
    assert body["payload"]["exercises"] == EXERCISES
    assert res["X-Robots-Tag"] == "noindex"

    link.refresh_from_db()
    assert link.view_count == 1


@pytest.mark.django_db
def test_unknown_slug_404(fitlog_tables):
    assert APIClient().get("/api/share-links/nope123456").status_code == 404


@pytest.mark.django_db
def test_revoked_link_is_410(fitlog_tables):
    link = make_link(revoked_at=timezone.now())
    assert APIClient().get(f"/api/share-links/{link.slug}").status_code == 410


@pytest.mark.django_db
def test_expired_link_is_410(fitlog_tables):
    link = make_link(expires_at=timezone.now() - timedelta(days=1))
    assert APIClient().get(f"/api/share-links/{link.slug}").status_code == 410


# ─── List + revoke ───────────────────────────────────────────────


@pytest.mark.django_db
def test_list_returns_only_my_links(owner_client, fitlog_tables):
    make_link()
    make_link(owner_user_id=FRIEND_ID, owner_first_name="Friend")
    res = owner_client.get("/api/share-links/")
    assert res.status_code == 200
    assert len(res.json()["links"]) == 1


@pytest.mark.django_db
def test_owner_can_revoke(owner_client, fitlog_tables):
    link = make_link()
    res = owner_client.delete(f"/api/share-links/{link.slug}")
    assert res.status_code == 200
    link.refresh_from_db()
    assert link.revoked_at is not None


@pytest.mark.django_db
def test_non_owner_cannot_revoke(friend_client, fitlog_tables):
    link = make_link()
    res = friend_client.delete(f"/api/share-links/{link.slug}")
    assert res.status_code == 404  # never 403
    link.refresh_from_db()
    assert link.revoked_at is None


# ─── Copy ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_friend_copies_snapshot_into_their_account(friend_client, template):
    link = make_link()
    res = friend_client.post(f"/api/share-links/{link.slug}/copy")
    assert res.status_code == 201

    copied = WorkoutTemplate.objects.get(id=res.json()["templateId"])
    assert copied.user_id == FRIEND_ID
    assert copied.exercises == EXERCISES
    assert copied.name == "Push Day A"


@pytest.mark.django_db
def test_copy_requires_auth(fitlog_tables):
    link = make_link()
    assert APIClient().post(f"/api/share-links/{link.slug}/copy").status_code == 401


@pytest.mark.django_db
def test_copy_of_revoked_link_is_410(friend_client, template):
    link = make_link(revoked_at=timezone.now())
    assert friend_client.post(f"/api/share-links/{link.slug}/copy").status_code == 410
