# Deploy Paperproof

This is a single-node pilot deployment: one app container, one Caddy container, one data volume, and internal TLS for `localhost`.

## Prerequisites

- Docker Engine with Compose v2.
- A small VM or local machine with at least 2 GB RAM.
- A real domain and DNS if you want public TLS. The default Caddyfile is for localhost.

## Configure

```bash
cp .env.example .env
chmod 600 .env
```

Set at least:

```bash
PAPERPROOF_ENV=prod
PAPERPROOF_SESSION_SECRET=<openssl rand -hex 32>
```

Optional:

```bash
PAPERPROOF_LLM_BASE_URL=https://api.openai.com/v1
PAPERPROOF_LLM_API_KEY=...
PAPERPROOF_LLM_MODEL=gpt-4.1-mini
PAPERPROOF_LLM_INPUT_COST_PER_MILLION=0.40
PAPERPROOF_LLM_OUTPUT_COST_PER_MILLION=1.60
```

Do not commit `.env`.

## Start

```bash
docker compose up -d --build
docker compose exec app paperproof auth set-password
```

Open https://localhost:8443. Caddy uses an internal certificate, so the browser will warn once. The app is never published directly; only Caddy exposes ports.

Seed the demo corpus if you want something to review:

```bash
docker compose exec app paperproof demo
```

## Health and logs

```bash
curl -k https://localhost:8443/healthz
docker compose logs -f app
docker compose logs -f caddy
```

The app logs one JSON object per request with a request ID. Health checks and static assets are excluded.

## Back up

```bash
docker compose exec app paperproof backup --out /app/data/backups/2026-11-26
docker compose cp app:/app/data/backups/2026-11-26 ./backups/2026-11-26
```

Copy backups off the host. The backup contains customer documents and is not encrypted by the app. Encrypt the destination.

## Restore

Restores go through a temporary volume, so a failed restore does not touch the live data.

```bash
./scripts/restore-volume.sh ./backups/2026-11-26
```

The script stops the app, restores into a temporary volume, verifies it, replaces the live volume contents, removes the temporary volume, and starts the app again. The session secret is not in the backup, so everyone signs in again. Users and password hashes are restored.

The compose project name is `paperproof`, so the default volume is `paperproof_paperproof_data`. Override with `PAPERPROOF_VOLUME` and `PAPERPROOF_IMAGE` if you rename the project or image.

## Upgrade and rollback

Before an upgrade:

```bash
docker tag paperproof:local paperproof:previous
git pull
docker compose build
docker compose up -d
```

Migrations run on startup. If the release is bad:

```bash
PAPERPROOF_TAG=previous docker compose up -d --no-build
```

If the schema changed, restore the last backup instead of rolling the image back.

## Real TLS

The shipped Caddyfile uses `tls internal` for localhost. For a real domain:

1. Point DNS at the host.
2. Replace `https://localhost` with `https://paperproof.example.com`.
3. Remove `tls internal`. Caddy obtains a Let's Encrypt certificate automatically.
4. Change the compose port mappings to `80:80` and `443:443`.
5. Update the HTTP redirect to the real domain.

## Smoke test

After a deploy and admin creation:

```bash
SMOKE_BASE_URL=https://localhost:8443 \
SMOKE_PASSWORD='...' \
uv run python scripts/smoke.py
```

The smoke test checks health, login, CSRF, the dashboard, the seeded document, and the request ID header.

## Security notes

- Keep `.env` at mode 0600 and out of version control.
- Publish only Caddy's ports, never the app's port.
- Set `PAPERPROOF_ENV=prod` so cookies are Secure.
- Use a real TLS certificate before exposing the host to the internet.
- Encrypt backups and test a restore before the pilot.
- There is one admin account. Lockout state is in process memory.
- Caddy terminates TLS; the app trusts the local Docker network.
