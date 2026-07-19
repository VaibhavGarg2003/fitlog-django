#!/usr/bin/env bash
# Render build step. `set -o errexit` = fail the deploy if any line fails,
# rather than shipping a half-built service.
set -o errexit

pip install -r requirements.txt

# Collect static files for whitenoise (the Django Admin's CSS/JS).
python manage.py collectstatic --no-input

# NOTE: migrations are NOT run here. DDL against the shared Supabase DB is
# a deliberate, rehearsed act (RUNBOOK) — run from a trusted machine with
# the prod DIRECT connection, never automatically during every deploy.
# Auto-migrating on deploy would also fail: Render can't reach Supabase's
# direct port reliably, and running DDL through the pooler is unsupported.
