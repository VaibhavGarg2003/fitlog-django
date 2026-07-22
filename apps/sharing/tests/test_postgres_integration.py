"""
Postgres integration tests (finding #7).

The unit suite runs on SQLite, which has no enum types, no RLS, and no FK
enforcement — so the Postgres-specific guarantees were only ever verified
by hand. These tests prove them automatically against a REAL Postgres.

They talk to the DB directly via psycopg (not the Django test-DB machinery),
and are SKIPPED unless INTEGRATION_DATABASE_URL is set — so a normal
`pytest` run is unaffected. The CI job (ci.yml) provisions a throwaway
Postgres, bootstraps the Prisma-owned schema, runs `manage.py migrate`
(which creates share_links + RLS + the FK), then sets the env and runs
`pytest -m postgres`.
"""

import os
import uuid

import psycopg
import pytest

INTEGRATION_URL = os.environ.get("INTEGRATION_DATABASE_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not INTEGRATION_URL,
        reason="INTEGRATION_DATABASE_URL not set — Postgres integration skipped",
    ),
]


@pytest.fixture()
def conn():
    with psycopg.connect(INTEGRATION_URL, autocommit=True) as c:
        yield c


def _make_user(conn, name="Test User") -> str:
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, name, created_at, updated_at) "
        "VALUES (%s, %s, %s, now(), now())",
        (uid, f"{uid}@x.com", name),
    )
    return uid


def _make_link(conn, owner_id: str) -> str:
    slug = uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO share_links "
        "(id, slug, owner_user_id, owner_first_name, kind, title, payload, "
        " view_count, created_at) "
        "VALUES (%s, %s, %s, %s, 'WORKOUT_TEMPLATE', 'T', '{}', 0, now())",
        (str(uuid.uuid4()), slug, owner_id, "Test"),
    )
    return slug


@pytest.mark.skipif(
    "supabase" in (INTEGRATION_URL or ""),
    reason="creates/drops a test role — needs superuser Postgres (CI), "
    "not managed Supabase where role DDL is restricted",
)
def test_rls_denies_non_owner_role(conn):
    """
    A role WITHOUT BYPASSRLS (the shape of Supabase's anon/authenticated,
    which the browser anon key maps to) must see ZERO rows in share_links,
    even with SELECT granted — because RLS is on with no policies.

    Runs in CI against a throwaway superuser Postgres. On Supabase this is
    skipped: its `postgres` role can't cleanly manage test roles, and the
    RLS lockdown there is already verified structurally at migration time.
    """
    owner = _make_user(conn)
    _make_link(conn, owner)

    conn.execute("DROP ROLE IF EXISTS itest_anon")
    conn.execute("CREATE ROLE itest_anon NOLOGIN")
    # Membership so the current role may SET ROLE into it. On Supabase the
    # `postgres` role isn't a full superuser and can only enter roles it's a
    # member of; on CI's superuser Postgres this grant is harmless.
    conn.execute("GRANT itest_anon TO CURRENT_USER")
    conn.execute("GRANT USAGE ON SCHEMA public TO itest_anon")
    conn.execute("GRANT SELECT ON share_links TO itest_anon")

    # Superuser bypasses RLS → sees the row.
    assert conn.execute("SELECT count(*) FROM share_links").fetchone()[0] >= 1

    conn.execute("SET ROLE itest_anon")
    try:
        denied = conn.execute("SELECT count(*) FROM share_links").fetchone()[0]
    finally:
        conn.execute("RESET ROLE")
    assert denied == 0, "RLS should hide all rows from a non-bypass role"

    # Data cleanup always runs (cascades the link); role teardown is
    # best-effort — managed Postgres (Supabase) restricts some role DDL,
    # and CI's superuser Postgres drops it cleanly either way.
    conn.execute("DELETE FROM users WHERE id = %s", (owner,))
    for stmt in (
        "REVOKE SELECT ON share_links FROM itest_anon",
        "REVOKE USAGE ON SCHEMA public FROM itest_anon",
        "REVOKE itest_anon FROM CURRENT_USER",
        "DROP ROLE IF EXISTS itest_anon",
    ):
        try:
            conn.execute(stmt)
        except psycopg.Error:
            pass


def test_fk_cascade_deletes_links_on_account_deletion(conn):
    """Deleting a user must cascade-delete their public share links (#5)."""
    owner = _make_user(conn)
    slug = _make_link(conn, owner)
    assert conn.execute(
        "SELECT count(*) FROM share_links WHERE slug = %s", (slug,)
    ).fetchone()[0] == 1

    conn.execute("DELETE FROM users WHERE id = %s", (owner,))
    assert conn.execute(
        "SELECT count(*) FROM share_links WHERE slug = %s", (slug,)
    ).fetchone()[0] == 0


def test_orphan_template_insert_is_rejected(conn):
    """
    The copy endpoint's 409 relies on the users FK rejecting a template for
    a non-existent account. Prove the FK actually fires.
    """
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO workout_templates "
            "(id, user_id, name, exercises, created_at, updated_at) "
            "VALUES (%s, %s, 'X', '[]', now(), now())",
            (str(uuid.uuid4()), "no-such-user"),
        )


def test_enum_column_accepts_valid_and_rejects_invalid(conn):
    """foods.source is a Postgres enum — valid values write, junk is refused."""
    fid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO foods (id, name, source, calories_per_100g, "
        "protein_per_100g, carbs_per_100g, fat_per_100g, created_at) "
        "VALUES (%s, 'itest food', 'MANUAL', 100, 10, 10, 2, now())",
        (fid,),
    )
    try:
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            conn.execute(
                "INSERT INTO foods (id, name, source, calories_per_100g, "
                "protein_per_100g, carbs_per_100g, fat_per_100g, created_at) "
                "VALUES (%s, 'bad', 'NOT_A_SOURCE', 1, 1, 1, 1, now())",
                (str(uuid.uuid4()),),
            )
    finally:
        conn.execute("DELETE FROM foods WHERE id = %s", (fid,))
