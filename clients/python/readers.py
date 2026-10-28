"""Ways to read a printer's counter. Each printer in config.json has a "reader" block:

  {"type": "simulated", "start": 0, "step": 3}            # for testing, counts up
  {"type": "file", "path": "C:\\\\logs\\\\counter.txt"}     # last line of a file holds the number
  {"type": "command", "command": "mytool.exe --pages"}    # command prints the number
  {"type": "http", "url": "http://192.168.1.21/pages", "json_path": "counters.total"}

Add a new type by adding a function to READERS. Readers return a number or raise.
"""
import json
import subprocess
import urllib.request


def _number(text):
    return float(str(text).strip().split()[0].replace(",", ""))


def _simulated(spec):
    spec["_n"] = spec.get("_n", spec.get("start", 0)) + spec.get("step", 1)
    return spec["_n"]


def _file(spec):
    with open(spec["path"], encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    return _number(lines[-1])


def _command(spec):
    out = subprocess.run(spec["command"], shell=True, capture_output=True, text=True, timeout=spec.get("timeout", 10))
    if out.returncode != 0:
        raise RuntimeError(f"command exited {out.returncode}: {out.stderr.strip()[:200]}")
    return _number(out.stdout)


def _http(spec):
    with urllib.request.urlopen(spec["url"], timeout=spec.get("timeout", 10)) as r:
        body = r.read().decode("utf-8", "replace")
    path = spec.get("json_path")
    if not path:
        return _number(body)
    data = json.loads(body)
    for part in path.split("."):
        data = data[part]
    return _number(data)


READERS = {"simulated": _simulated, "file": _file, "command": _command, "http": _http}


def read_value(spec):
    try:
        return READERS[spec["type"]](spec)
    except KeyError as e:
        if e.args and e.args[0] == spec.get("type"):
            raise ValueError(f"unknown reader type: {spec.get('type')}") from None
        raise
