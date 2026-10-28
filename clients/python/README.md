# IoT agent (Windows customer PC)

Reads each printer's page counter and sends it to `https://api.gellsoft.com`, using one device key per printer.
One agent process can serve many printers. A printer that fails (unreachable, unreadable counter, revoked key) never stops the others.

- [Keys at a glance](#keys-at-a-glance)
- [Files](#files)
- [1. Provision (your PC)](#1-provision-your-pc)
- [2. Configure readers](#2-configure-readers)
- [3. Install on the customer PC](#3-install-on-the-customer-pc)
- [Config reference](#config-reference)
- [How the agent behaves](#how-the-agent-behaves)
- [Operate](#operate)
- [Read the data](#read-the-data)
- [Troubleshooting](#troubleshooting)
- [Security checklist](#security-checklist)

## Keys at a glance

| Value | One per | Held by | Purpose |
|---|---|---|---|
| Device key | printer | the agent (`config.json` on the customer PC) | Send that printer's readings. Can also read that one printer. |
| Device ID | printer | you, dashboards, apps | Names the printer in read URLs. Not secret, useless without a key. |
| App key (customer key) | customer | the customer's dashboard/app | Read all of that customer's printers. Cannot send readings. |
| Admin key | you | your own PC only | Create customers, devices and keys. Never leaves your PC. |

Keys are shown once at creation and stored on the server only as hashes. They cannot be recovered, only revoked and replaced.

## Files

| File | Runs on | Purpose |
|---|---|---|
| `iot_client.py` | both | API client: offline queue (SQLite), batching, reads, admin calls |
| `agent.py` | customer PC | The multi-printer loop |
| `readers.py` | customer PC | How each printer's counter is read |
| `provision.py` | your PC | Creates customer/devices, writes the agent config |
| `install.ps1` / `uninstall.ps1` | customer PC | Install or remove the agent as a boot-time scheduled task |
| `config.example.json` | - | Sample config |

## 1. Provision (your PC)

Needs Python 3.9+ and `pip install requests`.

```powershell
$env:IOT_ADMIN_KEY = "<admin key>"          # this window only; do not persist it
cd clients\python

# new customer, plus an app key for their dashboard, plus two printers
python provision.py --customer-name "Acme" --customer-key-file acme-app-key.txt --out config-acme.json "EPSON=192.168.1.21" "HP=192.168.1.22"

# add printers to an existing customer
python provision.py --customer-id <customer-id> --out config-site2.json "Canon=192.168.2.10"
```

- `"Name=address"`: the address is stored in the printer's reader block for you to use. `"Name"` alone is fine.
- `--customer-key-file` is optional; skip it if there is no dashboard yet. Create one later with the admin endpoint `POST /v1/admin/customers/:id/keys`.
- It refuses to overwrite an existing output file, and it saves the keys of any devices already created if a later one fails.
- If it fails after creating the customer, the customer id is already printed. Re-run with `--customer-id`, not `--customer-name`, or you will create a duplicate customer.
- The output files hold secrets and are git-ignored. Do not commit or email them.

## 2. Configure readers

Provisioning writes every printer with a placeholder `simulated` reader that sends counting numbers. Replace each with a real reader before going live.

| Type | Fields | Reads |
|---|---|---|
| `simulated` | `start`, `step` | A fake counter, for testing |
| `file` | `path` | The number on the **last non-empty line** of a text file (`1,234` is read as 1234) |
| `command` | `command`, `timeout` (10s) | Runs the command and parses the first number it prints |
| `http` | `url`, `json_path` (optional, like `pages.total`), `timeout` | A number from the response body, or from a JSON field |

```json
{ "type": "file",    "path": "C:\\printers\\epson_counter.txt" }
{ "type": "command", "command": "C:\\tools\\getpages.exe 192.168.1.21" }
{ "type": "http",    "url": "http://192.168.1.22/counter", "json_path": "pages.total" }
```

Add a new type by adding a function to `READERS` in `readers.py`. Network printers usually expose the page count over SNMP; there is no SNMP reader yet.

Test before shipping (sends one real reading per printer): `python agent.py config-acme.json --once`

## 3. Install on the customer PC

1. Copy `agent.py`, `readers.py`, `iot_client.py`, `install.ps1`, `uninstall.ps1` and the config into one folder (USB stick or a secure share, not plain email/chat).
2. On the customer PC, install Python 3.9+ with **Add to PATH** ticked.
3. Open PowerShell **as Administrator** in that folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1 -ConfigPath .\config-acme.json
   ```
4. Delete the config copy you brought over; a locked copy now lives in `C:\IoTAgent`.

`install.ps1` does this, in order, and stops at the first failure:

1. Checks the files, the config, and Python 3.9+.
2. Stops any earlier install of the task.
3. Copies the agent to `C:\IoTAgent`.
4. Installs the config readable only by SYSTEM and Administrators.
5. Creates a private venv with `requests`.
6. Does one test cycle. If it fails, nothing is scheduled.
7. Registers the `IoTAgent` task (SYSTEM, at boot, restart every minute on failure, no time limit) and starts it.

Options: `-InstallDir` (default `C:\IoTAgent`; if you change it, update `queue_dir` and `log_path` in the config) and `-Force` (replace an existing install's config).

Network: outbound HTTPS to `api.gellsoft.com` on port 443. Nothing inbound is needed.

## Config reference

```json
{
  "api_url": "https://api.gellsoft.com",
  "interval_seconds": 30,
  "queue_dir": "C:\\IoTAgent\\queues",
  "log_path": "C:\\IoTAgent\\agent.log",
  "printers": [
    { "name": "EPSON", "device_key": "iot_...", "metric": "copies_printed",
      "reader": { "type": "file", "path": "C:\\printers\\epson.txt" } }
  ]
}
```

| Field | Default | Notes |
|---|---|---|
| `api_url` | `https://api.gellsoft.com` | |
| `interval_seconds` | 30 | Time between cycles (work time is subtracted; minimum 1s) |
| `queue_dir` | next to the agent | One SQLite queue file per printer (`queue_<name>.db`) |
| `log_path` | console only | Rotating log, 1 MB x 3 files |
| `printers[].name` | required | Used in logs and queue file names |
| `printers[].device_key` | required | That printer's own key |
| `printers[].metric` | `copies_printed` | Metric name sent with every reading (1-100 chars) |
| `printers[].reader` | required | See [Configure readers](#2-configure-readers) |

## How the agent behaves

- **Each cycle**, per printer: read the counter, queue the reading with the time it was taken (UTC), then try to send the queue.
- **Offline:** readings stay in the queue and are sent in batches of up to 500 once the connection returns. A reading is deleted from the queue only after the server answers `201`.
- **Server busy or down (`429`, `5xx`):** the queue is kept and retried next cycle.
- **Read failure:** that printer is skipped for the cycle and a warning is logged; others continue.
- **Key rejected (`401`/`403`):** that printer is disabled until the agent restarts. If all printers are disabled the agent exits with an error.
- **Rejected as invalid (`400`):** that batch is dropped and logged so it cannot block the queue forever.
- **Counter values are running totals** and are sent as read.

Known limitation: if a reply is lost after the server stored a batch, the retry stores it again (duplicate rows). A server-side unique constraint on `(device_id, metric, ts)` would remove this and is not added yet.

## Operate

| Task | Command (elevated PowerShell) |
|---|---|
| Status | `Get-ScheduledTask IoTAgent` |
| Logs | `Get-Content C:\IoTAgent\agent.log -Tail 50 -Wait` |
| Restart | `Stop-ScheduledTask IoTAgent; Start-ScheduledTask IoTAgent` |
| Update agent code | Copy the new `.py` files to `C:\IoTAgent`, then restart the task |
| Change a reader or key | Edit `C:\IoTAgent\config.json`, then restart the task |
| Remove | `.\uninstall.ps1` (add `-RemoveFiles` to delete config, queue and logs) |

**Replacing a key** (lost PC, leak, retired printer): revoke it with `DELETE /v1/admin/keys/:id` (the key id is in the server's `api_keys` table; there is no list endpoint yet), create a new device key, put it in that printer's `device_key`, and restart the task. If a PC is retired, revoke all its printers' keys.

## Read the data

With the app key (all of a customer's printers):

```powershell
$base = "https://api.gellsoft.com"
$c = @{ "x-api-key" = (Get-Content acme-app-key.txt -Raw).Trim() }

$devs = Invoke-RestMethod "$base/v1/devices" -Headers $c            # id, name, last_seen
Invoke-RestMethod "$base/v1/devices/$($devs[0].id)/latest" -Headers $c
Invoke-RestMethod "$base/v1/devices/$($devs[0].id)/metrics?metric=copies_printed&interval=hour&from=2026-10-29T00:00:00Z&to=2026-10-30T00:00:00Z" -Headers $c |
  Select-Object -ExpandProperty buckets | Format-Table bucket, count, last, max
```

Python: `IoTClient(key, queue_path=":memory:").devices() / .latest(id) / .metrics(id, "copies_printed", interval="hour")`.

Because the agent sends running totals, chart `last` (or `max`) per bucket. Copies in a period = this bucket's `last` minus the previous bucket's `last`. Do not use `sum`; it adds up running totals. Full API reference: see the root `README.md`.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `Python not found` in the installer | Install Python 3.9+ with Add to PATH, open a new PowerShell, retry |
| `pip install requests failed` | The PC is offline or a proxy blocks pypi.org |
| Test run fails in the installer | Read the message above it; usual causes are a wrong key, no route to `api.gellsoft.com`, or an unreadable counter |
| Log: `device key rejected` | Key revoked or wrong; issue a new key and update the config |
| Log: `could not read counter` | The reader's file, command or URL is wrong or unreachable from that PC |
| Log: `server rejected a batch as invalid` | A value or metric the API refuses (for example a non-number); check the reader output |
| Printer shows no recent `last_seen` | Task not running, PC offline, or the printer is disabled; check status and log |
| Values look like 1, 2, 3, ... | Still on the `simulated` reader |
| Task shows `Ready`, not `Running` | It stopped; check the log, then start it. The installer sets restart on failure. |
| `Execution policy` error | Use `powershell -ExecutionPolicy Bypass -File .\install.ps1 ...` |

## Security checklist

- Only device keys go on the customer PC. Never the admin key or an app key.
- One key per printer, so a leak or retirement affects one printer and revocation is surgical.
- The config is readable only by SYSTEM and Administrators. Do not loosen it.
- Do not put an app key in a public mobile app; it grants read access to all of that customer's data. Use per-user login for public apps (not built yet).
- Never commit or send configs and key files. `.gitignore` excludes `config*.json` (except the example) and `*-app-key.txt`.
- Rotate the admin key if it was ever shown on a shared screen: set a new `ADMIN_KEY` in the server's `.env` and restart the service.
