# IoT agent (Windows customer PC)

Reads each printer's page counter and sends it to `https://api.gellsoft.com`, one device key per printer.

## Keys at a glance
| Value | One per | Goes where |
|---|---|---|
| Device key | printer | the agent's `config.json` (customer PC) |
| Device ID | printer | read URLs; not secret |
| App key (customer key) | customer | the customer's dashboard/app; never on the printer PC |
| Admin key | you | your own PC only |

## 1. On your PC: provision
```powershell
$env:IOT_ADMIN_KEY = "<admin key>"
cd clients\python
python provision.py --customer-name "Acme" --customer-key-file acme-app-key.txt --out config-acme.json "EPSON=192.168.1.21" "HP=192.168.1.22"
```
Use `--customer-id <id>` instead of `--customer-name` to add printers to an existing customer.
Device keys are shown once; `config-acme.json` is their only copy. These files are git-ignored. Do not commit or email them.

Edit each printer's `reader` in the config (see `readers.py`); the default `simulated` reader sends fake numbers.
Test on your PC first: `python agent.py config-acme.json --once`.

## 2. Move to the customer PC
Copy `agent.py`, `readers.py`, `iot_client.py`, `install.ps1`, `uninstall.ps1` and the config (USB stick or a secure share) into one folder.

## 3. On the customer PC (Python 3.9+ installed, "Add to PATH" ticked)
Open PowerShell **as Administrator** in that folder:
```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -ConfigPath .\config-acme.json
```
It copies the agent to `C:\IoTAgent`, creates a private venv, locks the config to SYSTEM/Administrators, does a test send, then registers the `IoTAgent` scheduled task (starts at boot, restarts on failure, no login needed).
Afterwards, delete the config copy you brought over.

The customer PC needs outbound HTTPS to `api.gellsoft.com` (port 443). Nothing inbound.

## Operate
- Logs: `C:\IoTAgent\agent.log`
- Status: `Get-ScheduledTask IoTAgent`
- Restart: `Stop-ScheduledTask IoTAgent; Start-ScheduledTask IoTAgent`
- Update agent files: copy new `.py` files to `C:\IoTAgent`, then restart the task.
- Remove: `.\uninstall.ps1` (add `-RemoveFiles` to delete the config, queue and logs). Revoke the device keys on the server if the PC is retired.

## Read the data
```powershell
$c = @{ "x-api-key" = (Get-Content acme-app-key.txt -Raw).Trim() }
Invoke-RestMethod https://api.gellsoft.com/v1/devices -Headers $c
```
`GET /v1/devices/<id>/latest` and `/v1/devices/<id>/metrics?metric=copies_printed&interval=hour`.
The agent sends a running total: use `last`/`max` per bucket, not `sum`.
