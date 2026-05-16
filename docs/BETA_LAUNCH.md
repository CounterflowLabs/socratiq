# Closed-beta launch runbook

Solo-founder cookbook for the first paid release. Pairs with the high-level
plan in `~/.claude/plans/goofy-dancing-sparkle.md`.

## 1. Environment variables

### Backend (`backend/.env`)

Required:

```env
ENV=production
AUTH_MODE=jwt
JWT_SECRET_KEY=<random 32+ chars; e.g. python -c "import secrets;print(secrets.token_urlsafe(48))">
LLM_ENCRYPTION_KEY=<random 32+ chars>
GOOGLE_CLIENT_ID=<Google Cloud OAuth Web client ID>
ADMIN_EMAILS=you@example.com[,co-founder@example.com]
CORS_ORIGINS=https://app.yourdomain.com
SENTRY_DSN=<from sentry.io>
DATABASE_URL=postgresql+asyncpg://USER:PASS@host:5432/socratiq
REDIS_URL=redis://default:PASS@host:6379/0
CELERY_BROKER_URL=redis://default:PASS@host:6379/1
CELERY_RESULT_BACKEND=redis://default:PASS@host:6379/2
```

Platform LLM keys (set at least one chat provider):

```env
PLATFORM_ANTHROPIC_KEY=sk-ant-…
PLATFORM_OPENAI_KEY=sk-…
PLATFORM_OPENAI_EMBEDDING_KEY=sk-…       # optional, defaults to OPENAI_KEY
# PLATFORM_DEEPSEEK_KEY=…                 # optional cheaper fallback
# PLATFORM_QWEN_KEY=…                     # optional Chinese provider
# PLATFORM_ANTHROPIC_MODEL_ID=claude-sonnet-4-5
# PLATFORM_OPENAI_MODEL_ID=gpt-4o
# PLATFORM_ROUTE_MENTOR_CHAT=platform-anthropic   # override default routing
```

If any of `JWT_SECRET_KEY` or `LLM_ENCRYPTION_KEY` still equal their
`change-me-*` defaults while `ENV=production`, the backend refuses to start.

### Frontend (`frontend/.env`)

```env
BACKEND_URL=http://backend:8000          # read at runtime; override per env
NEXT_PUBLIC_GOOGLE_CLIENT_ID=<same as backend GOOGLE_CLIENT_ID>
```

## 2. Google OAuth setup

1. https://console.cloud.google.com → APIs & Services → Credentials.
2. Create OAuth 2.0 Client ID (type: Web).
3. Authorized JavaScript origins: `https://app.yourdomain.com`.
4. Authorized redirect URIs: not needed (we use the GIS `popup` flow).
5. Copy the Client ID into both `GOOGLE_CLIENT_ID` (backend) and
   `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (frontend).

## 3. First deploy

```bash
# 1. database
alembic upgrade head                  # already in backend Dockerfile entrypoint

# 2. seed platform LLM models (idempotent — re-run after key rotation)
uv run python -m scripts.seed_platform_models
#  or, container-side:
docker exec socratiq-backend python -m scripts.seed_platform_models

# 3. generate the first batch of beta codes
uv run python -m scripts.generate_codes --tier beta_30d --count 10 \
    --note "first cohort"
```

Tiers are defined in `app/services/activation.py::TIERS`. To add a new tier,
edit that dict and redeploy.

## 4. Sales / activation code flow

Mechanism: **out-of-band collection + manual code delivery**. No payment
provider integration. Pick the channel that matches your audience:

| Channel | Best when | Setup time |
| --- | --- | --- |
| Stripe Payment Link | overseas card, you want a hosted checkout page | 15 min |
| Lemon Squeezy | international, tax/VAT handled, MoR | 30 min |
| 微信 / 支付宝 个人收款 | 国内用户，少量交易 | 5 min |
| 闲鱼 / 小红书直连 | 国内首批冷启动 | 5 min |

Flow:

1. Buyer pays → receives confirmation (email / DM).
2. You run `python -m scripts.generate_codes --tier beta_30d --count 1
   --note "<buyer email or order id>"`, pipe the output to a follow-up
   message.
3. Buyer pastes the code at `https://app.yourdomain.com/redeem`. The page
   accepts the code, stamps `subscription_until` and `monthly_usd_cap` on
   the user, and lets them through.

Refunds: void in DB by setting `revoked_at` on the activation_codes row.
If the user already redeemed, the next authenticated request 402s.

```sql
UPDATE activation_codes SET revoked_at = now() WHERE code = 'SCQ-XXXX-...';
```

To extend a user's expiry manually:

```sql
UPDATE users SET subscription_until = subscription_until + interval '30 days'
WHERE email = 'user@example.com';
```

## 5. Backups

Daily `pg_dump` to S3-compatible storage (B2 / R2 / Wasabi all work fine).
Document and test the restore command before opening the beta.

```bash
# Backup
pg_dump --no-owner --no-acl "$DATABASE_URL_SYNC" \
  | gzip \
  | aws s3 cp - "s3://socratiq-backups/$(date +%F).sql.gz"

# Restore (into a scratch DB first to verify!)
aws s3 cp s3://socratiq-backups/2026-05-16.sql.gz - \
  | gunzip \
  | psql "$SCRATCH_DATABASE_URL"
```

Set it on a cron / a managed scheduler. Even `crontab -e` on the worker host
is fine for closed beta.

## 6. Observability

- **Sentry** — set `SENTRY_DSN`. Auto-init at app startup; FastAPI
  integration pulls request context.
- **Health** — `GET /health` returns `{ status, db, redis }`. Wire it to
  your host's health-check probe.
- **Usage logs** — every LLM call writes to `llm_usage_logs`. To watch a
  user's spend:

  ```sql
  SELECT model_name, SUM(estimated_cost_usd) AS usd,
         SUM(tokens_in) AS tin, SUM(tokens_out) AS tout
  FROM llm_usage_logs
  WHERE user_id = '<uuid>' AND created_at >= date_trunc('month', now())
  GROUP BY 1 ORDER BY 2 DESC;
  ```

## 7. Smoke test before opening the gate

Walk through this list in a clean browser session before sending the first
invite:

- [ ] `https://app.../login` → Google button → land on `/redeem`.
- [ ] Wrong code: shows red error, no redirect.
- [ ] Generated code: redeem → land on dashboard.
- [ ] Same code from a second account: 409 already-used.
- [ ] Set `monthly_usd_cap` to `0.01` for a test user → next `/chat`
      message returns 429 with the friendly notice.
- [ ] Revoke that user's code in SQL → next authenticated request 402s
      and the UI bounces back to `/redeem`.
- [ ] Sentry: `curl https://app/api/v1/auth/me` with a malformed JWT;
      confirm the 401 is *not* logged as an event (expected), then
      throw a deliberate 500 to see Sentry catch it.
- [ ] Backup: run the script, restore into a scratch DB, log in once.
- [ ] Import a YouTube source end-to-end (this exercises the full
      ingest → course → lessons → mentor pipeline against platform
      LLM keys).

## 8. What's intentionally NOT here

These are deferred to post-beta and tracked in
`~/.claude/plans/goofy-dancing-sparkle.md`:

- Auto-renewing subscriptions (Stripe webhook integration)
- Org / team / workspace model
- Email-based auth
- Password reset
- CI/CD pipeline (manual deploy is fine for closed beta)
- Admin dashboard
- Per-user usage UI
- Multi-region / HA
