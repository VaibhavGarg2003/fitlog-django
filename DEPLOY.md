# Deploying fitlog-django

The service runs on Render (free tier) via `render.yaml` (Blueprint). It
shares FitLog's Supabase Postgres, so **database migrations are a deliberate,
manual step — never run automatically on deploy** (`build.sh` intentionally
skips them). This mirrors the Next.js repo's `docs/learning/RUNBOOK.md`
"rehearse on dev, then perform on prod" discipline.

## One-time / after any migration change

Migrations must be applied from a trusted machine with the **prod DIRECT**
connection (port 5432), because:
- Render can't reliably reach Supabase's direct port, and
- DDL can't run through the transaction pooler (6543).

### 1. Rehearse on the dev Supabase project first

```bash
# .env points at the DEV project by default
python manage.py migrate
INTEGRATION_DATABASE_URL="<dev direct url>" pytest -m postgres   # optional
```

### 2. Perform on prod (deliberate)

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod \
DJANGO_SECRET_KEY="<prod secret>" \
DATABASE_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres?sslmode=require" \
SUPABASE_URL="https://<ref>.supabase.co" \
CORS_ALLOWED_ORIGINS="https://<vercel-domain>" \
python manage.py migrate
```

### 3. Verify prod

```sql
-- RLS must be ON for every Django-owned table (deny-all):
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname='public'
  AND (tablename LIKE 'django\_%' OR tablename LIKE 'auth\_%' OR tablename='share_links');
```
All rows should show `rowsecurity = true`. Then confirm `share_links` has the
`share_links_owner_user_id_fkey` FK to `users`.

### 4. Provision the admin (first deploy only)

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=... DATABASE_URL=... \
SUPABASE_URL=... CORS_ALLOWED_ORIGINS=... \
DJANGO_SUPERUSER_USERNAME=<u> DJANGO_SUPERUSER_EMAIL=<e> DJANGO_SUPERUSER_PASSWORD=<pw> \
python manage.py createsuperuser --noinput
```
Change the password after first login at `/admin`.

## Render dashboard: env vars to set (sync:false in render.yaml)

| Key | Value |
|---|---|
| `DJANGO_SECRET_KEY` | 50+ char random string |
| `DATABASE_URL` | prod Supabase **direct** URL + `?sslmode=require` |
| `SUPABASE_URL` | `https://<prod-ref>.supabase.co` (drives JWT verification) |
| `CORS_ALLOWED_ORIGINS` | the Vercel origin(s), comma-separated |

`ALLOWED_HOSTS` needs nothing — prod settings derive it from
`RENDER_EXTERNAL_HOSTNAME` automatically.

## Health check

`GET https://<service>.onrender.com/api/healthz` → `{"status":"ok","service":"fitlog-django"}`
