"""Multi-printer agent. One device key per printer, all read and sent from this one process.

  python agent.py                 # uses config.json next to the script (or the .exe)
  python agent.py C:\\IoTAgent\\config.json
  python agent.py --once          # one cycle then exit (for testing)

One printer failing (unreachable, bad reading, revoked key) never stops the others.
"""
import argparse
import json
import logging
import re
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from iot_client import AuthError, IoTClient
from readers import read_value

log = logging.getLogger("iot-agent")


def app_dir():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if not cfg.get("printers"):
        raise SystemExit("config.json has no printers")
    for p in cfg["printers"]:
        for field in ("name", "device_key", "reader"):
            if not p.get(field):
                raise SystemExit(f"printer entry is missing '{field}': {p.get('name', p)}")
    return cfg


def setup_logging(cfg):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [logging.StreamHandler()]
    if cfg.get("log_path"):
        handlers.append(RotatingFileHandler(cfg["log_path"], maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)


def build_printers(cfg):
    queue_dir = Path(cfg.get("queue_dir") or app_dir())
    queue_dir.mkdir(parents=True, exist_ok=True)
    api_url = cfg.get("api_url", "https://api.gellsoft.com")
    printers = []
    for p in cfg["printers"]:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", p["name"])
        printers.append(
            {
                "name": p["name"],
                "metric": p.get("metric", "copies_printed"),
                "reader": p["reader"],
                "client": IoTClient(p["device_key"], base_url=api_url, queue_path=str(queue_dir / f"queue_{slug}.db")),
                "active": True,
            }
        )
    return printers


def cycle(printers):
    for p in printers:
        if not p["active"]:
            continue
        try:
            p["client"].record(p["metric"], read_value(p["reader"]))
        except Exception as e:  # a bad read skips this printer for this cycle only
            log.warning("%s: could not read counter: %s", p["name"], e)
        try:
            sent = p["client"].flush()
            if sent:
                log.info("%s: sent %d reading(s)", p["name"], sent)
        except AuthError:
            p["active"] = False
            log.error("%s: device key rejected (revoked or wrong); this printer is disabled", p["name"])
        except ValueError as e:
            log.error("%s: %s", p["name"], e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default=str(app_dir() / "config.json"))
    ap.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = ap.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg)
    printers = build_printers(cfg)
    interval = cfg.get("interval_seconds", 30)
    log.info("agent started with %d printer(s), every %ss", len(printers), interval)

    try:
        while True:
            started = time.monotonic()
            cycle(printers)
            if not any(p["active"] for p in printers):
                log.error("all printers are disabled; exiting")
                return 1
            if args.once:
                return 0
            time.sleep(max(1.0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
