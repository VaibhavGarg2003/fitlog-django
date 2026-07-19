"""
Enable Row Level Security (deny-all) on every Django-owned table.

WHY: Supabase exposes the `public` schema through its PostgREST API using
the anon key that ships in the FitLog browser bundle. FitLog's tables were
locked down in Prisma migration 20260712010000; Django's tables
(share_links, django_*, auth_*) land in the SAME schema, so they need the
same lockdown — the discipline must live in BOTH migration systems.

Django itself connects as the `postgres` role (owner), which bypasses RLS
without FORCE — the app is unaffected, exactly like Prisma.

Implementation notes:
- RunPython + vendor check: the SQL is Postgres-only; unit tests run on
  SQLite and must skip it.
- Dynamic loop over pg_tables: idempotent, and catches every django_*/
  auth_* table regardless of contrib migration ordering.
- Dependencies pin contrib apps so their tables exist before this runs.
"""

from django.db import migrations

LOCKDOWN_SQL = """
DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public'
      AND (
        tablename LIKE 'django\\_%'
        OR tablename LIKE 'auth\\_%'
        OR tablename = 'share_links'
      )
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;
"""


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # SQLite (tests) has no RLS — and no PostgREST exposure
    # Raw cursor with NO params: psycopg only rewrites %-placeholders when
    # params are passed, and this SQL contains format('%I') which psycopg
    # would otherwise reject as an invalid placeholder.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCKDOWN_SQL)


def noop(apps, schema_editor):
    # Leaving RLS enabled on rollback is safe (deny-all, owner bypasses).
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sharing", "0001_initial"),
        # Contrib tables must exist before the lockdown loop runs.
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("sessions", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(enable_rls, noop),
    ]
