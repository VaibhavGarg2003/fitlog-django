"""
Add a FK from share_links.owner_user_id → users(id) ON DELETE CASCADE.

WHY: share_links is Django-owned but references a Prisma-owned user. Without
this constraint, deleting an account leaves its PUBLIC snapshots reachable
until expiry (or forever, for no-expiry links) — a privacy/retention leak,
since the user's own templates DO cascade away via Prisma's FKs.

The constraint lives ON the Django-owned table pointing AT users(id), so it
never alters the users schema (Prisma stays the owner). "The database
defends itself" — the same principle as the meal unique constraint and RLS.

Postgres-only (SQLite tests skip it). Orphan rows are deleted first so the
constraint can be created even if a stray owner_user_id exists.
"""

from django.db import migrations

ADD_FK = """
DELETE FROM share_links
WHERE owner_user_id NOT IN (SELECT id FROM users);

ALTER TABLE share_links
  ADD CONSTRAINT share_links_owner_user_id_fkey
  FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE;
"""

DROP_FK = """
ALTER TABLE share_links DROP CONSTRAINT IF EXISTS share_links_owner_user_id_fkey;
"""


def add_fk(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(ADD_FK)


def drop_fk(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_FK)


class Migration(migrations.Migration):
    dependencies = [
        ("sharing", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunPython(add_fk, drop_fk),
    ]
