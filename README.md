# fitlog-django

FitLog's **second service** — Django 5 + DRF alongside the
[Next.js app](https://github.com/VaibhavGarg2003/FitLog). It owns what
serverless is bad at and what Django is uniquely good at:

- **Share links** — public read-only snapshots of workouts/plans (D3)
- **Django Admin** over the food database — a CRUD back-office in ~20 lines (D3)
- **Scheduled jobs** — weekly-insight pre-generation, keepalive (D6)

## Architecture

```
Browser ──► Next.js on Vercel (unchanged) ──► Supabase Postgres
   │                                              ▲
   │  Authorization: Bearer <supabase JWT>        │  django-owned tables:
   ▼                                              │  share_links, page_views
Django + DRF on Render ───────────────────────────┘
   /api/healthz  /api/whoami  (+ share-links, admin, cron)
```

- **One identity provider, two verifiers.** Django verifies the SAME
  Supabase JWT the browser already holds, against the project's public
  JWKS (`apps/core/authentication.py`). No passwords here, no second login.
- **Shared DB, strict table ownership.** Prisma migrates FitLog's tables;
  Django migrates only its own and maps FitLog's with `managed = False`.

## Local development

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -r requirements-dev.txt
cp .env.example .env            # fill in dev Supabase values
python manage.py runserver      # settings: config.settings.dev
```

Smoke test: `curl http://localhost:8000/api/healthz`

## Tests & lint

```bash
pytest        # unit tests (JWT auth suite runs without any network/DB)
ruff check .  # lint (incl. security + django rules)
```

## Settings

`config/settings/{base,dev,prod}.py` — manage.py defaults to dev,
wsgi.py (gunicorn) defaults to prod. Prod requires `DJANGO_SECRET_KEY`
and `DJANGO_ALLOWED_HOSTS` from the host environment and boots with
`DEBUG=False`, HTTPS hardening, and whitenoise static files.

## Deploy (D4 — Render)

Gunicorn entry: `gunicorn config.wsgi` — config arrives via Render env vars.
