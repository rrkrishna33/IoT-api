"""Ways to read a printer's counter. Each printer in config.json has a "reader" block:

  {"type": "simulated", "start": 0, "step": 3}            # for testing, counts up
  {"type": "file", "path": "C:\\\\logs\\\\counter.txt"}     # last line of a file holds the number
  {"type": "command", "command": "mytool.exe --pages"}    # command prints the number
  {"type": "http", "url": "http://192.168.1.21/pages", "json_path": "counters.total"}
  {"type": "modbus", "port": "COM3", "slave": 1, "register": 0, "format": "uint32"}  # RS485 Modbus RTU

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


_MODBUS_WORD_ORDER = {"big": 0, "little": 1, "big_swap": 2, "little_swap": 3}  # minimalmodbus BYTEORDER_*


def _modbus(spec):
    """Modbus RTU over RS485 (pip install minimalmodbus). Machines on one bus share the port, each with its own slave id."""
    import minimalmodbus

    inst = spec.get("_instrument")
    if inst is None:
        inst = minimalmodbus.Instrument(spec["port"], int(spec.get("slave", 1)))
        inst.serial.baudrate = int(spec.get("baudrate", 9600))
        inst.serial.parity = spec.get("parity", "N")
        inst.serial.stopbits = int(spec.get("stopbits", 1))
        inst.serial.bytesize = 8
        inst.serial.timeout = float(spec.get("timeout", 1))
        inst.close_port_after_each_call = True
        spec["_instrument"] = inst
    reg = int(spec["register"])  # 0-based protocol address: holding register 40001 is 0
    fc = int(spec.get("function", 3))  # 3 = holding registers, 4 = input registers
    fmt = spec.get("format", "uint16")
    order = _MODBUS_WORD_ORDER[spec.get("word_order", "big")]
    if fmt in ("uint16", "int16"):
        value = inst.read_register(reg, functioncode=fc, signed=fmt == "int16")
    elif fmt in ("uint32", "int32"):
        value = inst.read_long(reg, functioncode=fc, signed=fmt == "int32", byteorder=order)
    elif fmt == "float32":
        value = inst.read_float(reg, functioncode=fc, byteorder=order)
    else:
        raise ValueError(f"unknown modbus format: {fmt}")
    return value * spec.get("scale", 1)


READERS = {"simulated": _simulated, "file": _file, "command": _command, "http": _http, "modbus": _modbus}


def read_value(spec):
    try:
        return READERS[spec["type"]](spec)
    except KeyError as e:
        if e.args and e.args[0] == spec.get("type"):
            raise ValueError(f"unknown reader type: {spec.get('type')}") from None
        raise
