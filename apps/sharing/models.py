"""
Sharing models
══════════════

TWO KINDS OF MODEL LIVE HERE — the table-ownership rule made visible:

1. ShareLink — DJANGO-OWNED. Django migrations create and evolve it.
2. WorkoutTemplate / FitLogUser — FITLOG-OWNED (Prisma migrates them).
   Mapped with `managed = False`: "I read/write ROWS in this table, but
   I don't own its SCHEMA." Prisma column types drive the field choices:
   Prisma String ids are TEXT (so CharField, not UUIDField) and Prisma
   enums are real Postgres enum types (so PgEnumField below).
"""

import secrets
import uuid

from django.db import models


class PgEnumField(models.CharField):
    """
    CharField over a Postgres ENUM column.

    WHY: psycopg3 binds Python str parameters as `text`, and Postgres has
    no implicit text→enum conversion for bound parameters — INSERT/UPDATE
    into an enum column fails with "column is of type X but expression is
    of type text". Overriding get_placeholder casts the parameter
    (`%s::"EnumName"`) so writes work. Reads are unaffected (enums come
    back as strings). Don't filter on these fields without an explicit
    cast — admin list_filter is deliberately not used on them.
    """

    def __init__(self, *args, enum_name: str, **kwargs):
        self.enum_name = enum_name
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["enum_name"] = self.enum_name
        return name, path, args, kwargs

    def get_placeholder(self, value, compiler, connection):
        # The ::cast is Postgres syntax; on SQLite (unit tests) the column
        # is plain TEXT and needs a bare placeholder.
        if connection.vendor != "postgresql":
            return "%s"
        return f'%s::"{self.enum_name}"'


def generate_slug() -> str:
    """
    Unguessable public handle — ~11 URL-safe chars, 64 bits of entropy.
    NEVER sequential ids: /s/1, /s/2 would let strangers enumerate every
    shared plan (IDOR by design flaw).
    """
    return secrets.token_urlsafe(8)


class ShareLink(models.Model):
    """
    A SNAPSHOT of something the user chose to share.

    The payload is frozen at share time (JSONB): editing the original
    later must not change what the link shows — live links would leak
    future private edits. Same data live-and-editable stays normalized
    in FitLog's tables; frozen-and-read-only lives here as JSON. Two
    representations, two correct answers.
    """

    class Kind(models.TextChoices):
        WORKOUT_TEMPLATE = "WORKOUT_TEMPLATE"
        NUTRITION_DAY = "NUTRITION_DAY"  # future
        WORKOUT_SESSION = "WORKOUT_SESSION"  # future

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.CharField(max_length=32, unique=True, default=generate_slug)
    # Supabase user id — TEXT in the users table, so CharField here.
    owner_user_id = models.CharField(max_length=64, db_index=True)
    # Snapshotted at share time. First name ONLY — a share shows the plan
    # and a name, never email/weight/goals/body data.
    owner_first_name = models.CharField(max_length=40, blank=True, default="")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=120)
    payload = models.JSONField()
    view_count = models.IntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "share_links"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}:{self.slug}"


# ─── FitLog-owned tables (managed=False — Prisma is the schema boss) ───


class WorkoutTemplate(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    user_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    split_type = PgEnumField(
        enum_name="WorkoutSplit", max_length=32, null=True, blank=True
    )
    exercises = models.JSONField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "workout_templates"

    def __str__(self):
        return self.name


class FitLogUser(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    email = models.CharField(max_length=255)
    # null=True mirrors Prisma's nullable TEXT column — we MUST match the
    # existing schema, so Django's ""-over-NULL convention doesn't apply.
    name = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001

    class Meta:
        managed = False
        db_table = "users"

    def __str__(self):
        return self.email
