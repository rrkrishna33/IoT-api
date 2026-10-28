# IoT API

Collects readings from machines (for example copies printed per printer) and serves them to dashboards and apps.
Live at `https://api.gellsoft.com`. Node 22 + Fastify + PostgreSQL, behind Caddy.

```
Printer PC (agent) --HTTPS, device key--> api.gellsoft.com (Caddy) --> Node API :4000 --> PostgreSQL "iot"
Dashboard / app   --HTTPS, app key-----^
```

- [Repository layout](#repository-layout)
- [Concepts and keys](#concepts-and-keys)
- [API reference](#api-reference)
- [Local development](#local-development)
- [Deployment on the VM](#deployment-on-the-vm)
- [Operations](#operations)
- [Security model](#security-model)
- [Limitations and roadmap](#limitations-and-roadmap)

## Repository layout

| Path | Purpose |
|---|---|
| `src/server.js` | Fastify app: security headers, CORS, rate limit, routes |
| `src/auth.js` | Key generation/hashing, admin and API-key checks |
| `src/routes/admin.js` | Create customers, devices, keys; revoke keys |
| `src/routes/readings.js` | Ingest readings; list devices; latest values; bucketed metrics |
| `migrations/` | SQL migrations, applied by `npm run migrate` |
| `scripts/migrate.js` | Minimal migration runner (tracks `schema_migrations`) |
| `ecosystem.config.cjs` | pm2 process definition (what the VM uses) |
| `deploy/` | Caddy block (`Caddyfile.snippet`) and an alternative systemd unit |
| `clients/python/` | Windows agent, provisioning script, installer. See its README. |

## Concepts and keys

- **Customer**: a client company. **Device**: one machine/printer belonging to a customer. **Reading**: `(device, metric, value, timestamp)`. New kinds of data are just new `metric` names; no schema change.
- Three kinds of key, sent as `x-api-key: <key>` (or `Authorization: Bearer <key>`):

| Key | Scope | Can |
|---|---|---|
| Admin key (`ADMIN_KEY` in `.env`) | whole system | use `/v1/admin/*` only |
| Device key | one device | send readings; read that device |
| Customer (app) key | one customer | read all that customer's devices; cannot send readings |

- Keys look like `iot_<43 random chars>`. Only their SHA-256 is stored, so they are shown once and cannot be recovered, only revoked.
- The key, not the request, decides which device a reading belongs to. A device cannot write for another device.

## API reference

Base URL `https://api.gellsoft.com`. Bodies and responses are JSON. Timestamps are ISO 8601 (UTC recommended).

### Public
| Method and path | Result |
|---|---|
| `GET /health` | `{"ok":true}` (also checks the database) |

### Admin (admin key)
| Method and path | Body | Result |
|---|---|---|
| `POST /v1/admin/customers` | `{"name"}` | `201` customer `{id,name,created_at}` |
| `POST /v1/admin/customers/:id/devices` | `{"name"}` | `201` `{device, api_key}`; the device key is shown once |
| `POST /v1/admin/customers/:id/keys` | none | `201` `{api_key}`; a customer (app) key, shown once |
| `DELETE /v1/admin/keys/:id` | none | `{revoked:true}`, or `404` |

### Send readings (device key)
`POST /v1/readings`, either one reading or a batch of 1-500:
```json
{ "metric": "copies_printed", "value": 120, "ts": "2026-10-29T10:00:00Z" }
{ "readings": [ { "metric": "copies_printed", "value": 5, "ts": "..." }, { "metric": "copies_printed", "value": 7 } ] }
```
`metric` is 1-100 chars, `value` a number, `ts` optional (defaults to server time). Returns `201 {"accepted": n}`. A customer key gets `403`.

### Read (device key for its own device, customer key for any of its devices)
| Method and path | Result |
|---|---|
| `GET /v1/devices` | `[{id, name, created_at, last_seen}]` |
| `GET /v1/devices/:id/latest` | newest `{metric, value, ts}` for each metric |
| `GET /v1/devices/:id/metrics?metric=&interval=&from=&to=` | `{metric, interval, from, to, buckets:[{bucket,count,sum,avg,min,max,last}]}` |

`metrics`: `metric` is required; `interval` is `minute|hour|day|week|month` (default `hour`); `from`/`to` default to the last 24 hours. For running totals (page counters) chart `last` or `max`, not `sum`.

### Errors
`400` invalid body or query, `401` missing/invalid/revoked key, `403` wrong key type for this action, `404` not found (including another customer's device), `429` rate limit (300 requests/minute per client IP).

## Local development

Needs Node 22+ and a PostgreSQL 13+ database.

```powershell
npm install
copy .env.example .env      # set DATABASE_URL and a long random ADMIN_KEY
npm run migrate
npm run dev                 # http://127.0.0.1:4000/health
```

Generate an admin key: `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`

`.env` settings: `PORT` (4000), `HOST` (127.0.0.1), `DATABASE_URL`, `ADMIN_KEY`, `CORS_ORIGINS` (comma-separated browser origins; empty means none).

## Deployment on the VM

Current production layout (Ubuntu, Caddy for TLS, pm2 for processes, PostgreSQL local only):

| Item | Value |
|---|---|
| Code | `/opt/IoT-api` (git clone of this repo) |
| Process | pm2 app `iot-api`, run as the unprivileged `iotapi` user, listening on `127.0.0.1:4000` |
| Config | `/opt/IoT-api/.env`, mode 600, owned by `iotapi` |
| Database | PostgreSQL database `iot`, role `iot_user` (separate from the other apps' databases) |
| TLS and routing | Caddy: a named `api.gellsoft.com` block proxying to `127.0.0.1:4000` (`deploy/Caddyfile.snippet`) |
| DNS | `api.gellsoft.com` A record to the VM, **DNS only** (grey cloud). If proxied through Cloudflare, set SSL mode to Full (strict). |

**First-time setup** (already done on the current VM):
1. Create the DB role and database, write `.env` with a random password and `ADMIN_KEY`.
2. `npm ci --omit=dev`, then `npm run migrate` as `iotapi`.
3. `pm2 start ecosystem.config.cjs && pm2 save` (the VM already has pm2's boot service).
4. Append `deploy/Caddyfile.snippet` to `/etc/caddy/Caddyfile`, run `caddy validate`, then `systemctl reload caddy`.

**Deploy an update:**
```bash
cd /opt/IoT-api && git pull && npm ci --omit=dev && npm run migrate && pm2 restart iot-api
```
`npm run migrate` applies only new files in `migrations/`. Add schema changes as new numbered `.sql` files; never edit an applied one.

`deploy/iot-api.service` is a systemd alternative to pm2. Run one or the other, not both (they would fight over port 4000).

## Operations

- Health: `curl https://api.gellsoft.com/health`
- Status and logs: `pm2 list`, `pm2 logs iot-api --lines 50`
- Database console: `sudo -u postgres psql -d iot`
- From a GUI tool: Postgres listens on localhost only; use an SSH tunnel (`ssh -L 5433:127.0.0.1:5432 root@<vm>`) and connect to `127.0.0.1:5433`.
- Back up (recommended; not scheduled yet): `sudo -u postgres pg_dump iot | gzip > /root/backups/iot-$(date +%F).sql.gz`
- Rotate the admin key: set a new `ADMIN_KEY` in `.env`, `pm2 restart iot-api`.
- Revoke a key: `DELETE /v1/admin/keys/:id` (look up ids in `api_keys`: `select id, customer_id, device_id, label, created_at, revoked_at from api_keys;`).

## Security model

- Postgres is bound to localhost; only the API is public, through Caddy with automatic HTTPS and HSTS.
- Keys are random and stored as SHA-256 hashes. Device keys are per machine and revocable; customer keys are read-only.
- Admin routes compare the admin key in constant time. Never put the admin key on a customer PC, in an app, or in Git.
- Rate limit of 300 requests/minute per client IP; request bodies are limited to 1 MB and batches to 500 readings; inputs are schema-validated.
- The API runs as an unprivileged user with its own database role.
- `.gitignore` excludes `.env`, generated agent configs and key files.

## Limitations and roadmap

Not built yet:
- Per-user login (JWT) for dashboards and mobile apps. Today apps use a customer key, which should not be embedded in public apps.
- Duplicate protection: a retried batch can store the same reading twice (planned: unique `(device_id, metric, ts)`).
- An endpoint to list keys, and per-device or per-key rate limits.
- "Copies per period" (difference of running totals), raw-reading listing with pagination, and CSV export.
- An SNMP reader in the agent.
- Host hardening and backups on the VM: the `ufw` firewall is off, and database backups are not scheduled.
