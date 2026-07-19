"""
Shared pytest fixtures.

pytest-django builds the test DB from MIGRATIONS, and managed=False
models deliberately produce no SQL (Prisma owns those schemas in real
life). So we extend django_db_setup: right after the test database is
created — and BEFORE any test opens its transaction (SQLite's schema
editor refuses to run inside one) — create the unmanaged tables with
schema_editor, which ignores the managed flag.
"""

import pytest
from django.db import connection


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    from apps.foods.models import Food
    from apps.sharing.models import FitLogUser, WorkoutTemplate

    with django_db_blocker.unblock():
        existing = connection.introspection.table_names()
        with connection.schema_editor(atomic=False) as editor:
            for model in (WorkoutTemplate, FitLogUser, Food):
                if model._meta.db_table not in existing:
                    editor.create_model(model)
    yield


@pytest.fixture()
def fitlog_tables(db):
    """Marker fixture: the FitLog tables exist session-wide (see above);
    this just declares a test's dependency on the database."""
    yield
