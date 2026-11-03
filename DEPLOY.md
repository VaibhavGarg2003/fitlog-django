# Deploying fitlog-django

The service runs on Render (free tier) via `render.yaml` (Blueprint). It
shares FitLog's Supabase Postgres, so **database migrations are a deliberate,
manual step — never run automatically on deploy** (`build.sh` intentionally
skips them). This mirrors the Next.js repo's `docs/learning/RUNBOOK.md`
"rehearse on dev, then perform on prod" discipline.

## One-time / after any migration change

Migrations must be applied from a trusted machine with the **prod DIRECT**
connection (port 5432, host `db.<ref>.supabase.co`), because:
- **Render cannot reach it at all** — that hostname resolves ONLY to an
  IPv6 address, and Render's free tier has no IPv6 egress. (Confirmed via
  `nslookup`: direct → IPv6 only; the pooler host → real IPv4 addresses.)
  This is exactly why Render's *runtime* `DATABASE_URL` must be the
  **session pooler**, not direct — see the table below. Don't reuse the
  direct URL for both purposes; they solve different problems.
- DDL can't run through the *transaction* pooler (port 6543) either — a
  second, independent reason migrations need the direct connection,
  which only a machine with IPv4+IPv6 (or IPv6) egress can reach.

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
| `DATABASE_URL` | prod Supabase **SESSION POOLER** URL — host `aws-<n>-<region>.pooler.supabase.com`, **port 5432** (not 6543), username `postgres.<project-ref>`, + `?sslmode=require`. NOT the direct connection — see the IPv6 note above. |
| `SUPABASE_URL` | `https://<prod-ref>.supabase.co` (drives JWT verification) |
| `CORS_ALLOWED_ORIGINS` | the Vercel origin(s), comma-separated |

**Why session pooler and not the 6543 transaction pooler?** Supabase's own
guidance: session mode (5432) is for persistent server processes (this
service, running gunicorn all day); transaction mode (6543) is for
serverless functions with many short-lived connections (that's what the
*Next.js* app on Vercel uses instead). Each platform gets the pooling mode
suited to how it holds connections.

`ALLOWED_HOSTS` needs nothing — prod settings derive it from
`RENDER_EXTERNAL_HOSTNAME` automatically.

## Health check

`GET https://<service>.onrender.com/api/healthz` → `{"status":"ok","service":"fitlog-django"}`

## Live chat (apps.chat) — turning it on in production

The service now runs **ASGI** (uvicorn, one process) so it can hold the
live-chat WebSockets next to the share-link API. Chat messages live in
Postgres (written by Next.js); this service only pushes IDs-only "something
changed" hints to open tabs. If it is down or asleep, chat still works —
clients poll every 30 s.

Do these **in order**, rehearsing each on dev first:

1. **Least-privilege DB role** (Next.js repo, `db/roles/005_django_runtime_role.sql`),
   as `postgres`:
   ```bash
   psql "$SUPERUSER_DIRECT_URL" -v django_password="$(openssl rand -hex 32)" \
     -f db/roles/005_django_runtime_role.sql
   ```
   Then change Render's `DATABASE_URL` to the **session pooler** with that role:
   `postgresql://fitlog_django.<ref>:<pw>@<pooler-host>:5432/postgres`.
   Deploy and check share links still work (create / open / copy) and that
   `/admin` loads. Migrations keep running by hand **as postgres** (above).

2. **Secrets** — the same two values on Render AND Vercel (≥32 chars, different):
   `CHAT_WS_TICKET_SECRET`, `CHAT_RELAY_SECRET`. On Render also set
   `CHAT_WS_ALLOWED_ORIGINS=https://<your app origin>` (comma-separated if
   several). On Vercel also set `CHAT_WS_URL=wss://<render host>/ws/inbox/`
   and `CHAT_RELAY_URL=https://<render host>/internal/chat/events`.

3. **Deploy Django first** (new start command from `render.yaml`), check
   `https://<render host>/api/chat/healthz` → `{"live": true, ...}`, then
   redeploy Vercel.

4. **Keep it awake** (free tier sleeps after 15 min without traffic):
   - cron-job.org (free): GET `https://<render host>/api/healthz` every 10 min.
   - UptimeRobot (free): HTTP monitor on the same URL every 5 min, email alerts.
   One always-awake free service uses ~744 of the workspace's 750 free
   hours/month — **never add a second always-awake free service** to this
   Render workspace. Watch outbound bandwidth too (5 GB/month on Hobby).

5. **Real-device check**: two phones, two accounts → a message appears on
   the other phone within a second; turn on airplane mode → "Live updates
   paused" → messages still arrive within ~30 s after reconnecting.

**Rollback**: unset the two secrets on Render (live chat switches off, clients
fall back to polling) or redeploy the previous commit. The share-link API is
unaffected by either.

**Limits** (deliberate, single process): 50 sockets total, 5 per user
(`CHAT_MAX_CONNECTIONS*`) — raise only after a load test. Scaling to more
than one process requires `channels_redis` first.
