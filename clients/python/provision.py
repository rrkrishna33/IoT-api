"""Run on YOUR PC (needs the admin key). Creates one device per printer for a customer
and writes the agent's config.json with each printer's own key.

  $env:IOT_ADMIN_KEY = "..."
  # existing customer
  python provision.py --customer-id <id> --out config-site1.json "Printer 1=192.168.1.21" "Printer 2=192.168.1.22"
  # brand-new customer (created first), plus a read-only key for their apps
  python provision.py --customer-name "Acme Printers" --customer-key-file acme-app-key.txt --out config-acme.json "Printer 1"

Device keys are shown only once by the server; the written files are their only copy.
Every reader is a "simulated" placeholder: edit each one to a real reader (see readers.py).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from iot_client import IoTClient


def main():
    ap = argparse.ArgumentParser()
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--customer-id", help="add printers to an existing customer")
    who.add_argument("--customer-name", help="create a new customer with this name first")
    ap.add_argument("--customer-key-file", help="also create a customer (app) key and save it to this file")
    ap.add_argument("--out", default="config.json")
    ap.add_argument("--api-url", default="https://api.gellsoft.com")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("printers", nargs="+", help='"Name" or "Name=address"')
    args = ap.parse_args()

    out = Path(args.out)
    key_file = Path(args.customer_key_file) if args.customer_key_file else None
    for path in (out, key_file):
        if path and path.exists():
            sys.exit(f"{path} already exists; refusing to overwrite (it may hold keys that cannot be recovered)")
    if "IOT_ADMIN_KEY" not in os.environ:
        sys.exit("set IOT_ADMIN_KEY first")

    admin = IoTClient(os.environ["IOT_ADMIN_KEY"], base_url=args.api_url, queue_path=":memory:")
    customer_id = args.customer_id
    if args.customer_name:
        customer_id = admin.create_customer(args.customer_name)["id"]
        print(f"created customer {args.customer_name}: id {customer_id}")
    if key_file:
        key_file.write_text(admin.create_customer_key(customer_id)["api_key"], encoding="utf-8")
        print(f"wrote customer app key to {key_file}")
    cfg = {
        "api_url": args.api_url,
        "interval_seconds": args.interval,
        "queue_dir": "C:\\IoTAgent\\queues",
        "log_path": "C:\\IoTAgent\\agent.log",
        "printers": [],
    }
    created = []
    try:
        for spec in args.printers:
            name, _, address = spec.partition("=")
            dev = admin.create_device(customer_id, name)
            created.append(name)
            reader = {"type": "simulated", "note": "replace with a real reader"}
            if address:
                reader["address"] = address
            cfg["printers"].append(
                {"name": name, "device_id": dev["device"]["id"], "device_key": dev["api_key"], "reader": reader}
            )
            print(f"created {name}: device id {dev['device']['id']}")
    finally:
        # Write whatever was created, even if a later call failed, so no key is lost.
        if cfg["printers"]:
            out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            print(f"wrote {out} with {len(cfg['printers'])} printer(s). Keep it private; copy it to the customer PC as config.json.")


if __name__ == "__main__":
    main()
