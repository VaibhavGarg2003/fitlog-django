"""
Test settings — hermetic by force.

Unit tests must not touch ANY real service: the suite runs on in-memory
SQLite even when a developer's .env points DATABASE_URL at the dev
Supabase project. (Without this, pytest-django would try to create its
throwaway test database on the real Postgres server.)
"""

from .dev import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Fast, deterministic password hashing for any auth-table fixtures.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
