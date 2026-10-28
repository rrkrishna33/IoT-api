"""Small client for the IoT API (https://api.gellsoft.com).

pip install requests

Machine agent (device key): record() readings, they are queued in a local SQLite
file and sent in batches by flush(), so nothing is lost while offline.
Reader apps (customer or device key): devices(), latest(), metrics().
Admin helpers (admin key): create_customer(), create_device(), create_customer_key().
"""
import json
import sqlite3
import time

import requests

BASE_URL = "https://api.gellsoft.com"
MAX_BATCH = 500  # server limit per request


class AuthError(Exception):
    """The key was rejected (401/403). Retrying will not help."""


class IoTClient:
    def __init__(self, api_key, base_url=BASE_URL, queue_path="iot_queue.db", timeout=10):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["x-api-key"] = api_key
        self.db = sqlite3.connect(queue_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()

    # ---- sending (device key) ----
    def record(self, metric, value, ts=None):
        """Queue a reading. ts is a UTC ISO string; defaults to now (the time it was taken)."""
        ts = ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        body = json.dumps({"metric": metric, "value": value, "ts": ts})
        self.db.execute("INSERT INTO queue (body) VALUES (?)", (body,))
        self.db.commit()

    def flush(self):
        """Send queued readings in batches. Returns how many were accepted.
        Network errors, 429 and 5xx keep the queue for the next attempt."""
        sent = 0
        while True:
            rows = self.db.execute("SELECT id, body FROM queue ORDER BY id LIMIT ?", (MAX_BATCH,)).fetchall()
            if not rows:
                return sent
            payload = {"readings": [json.loads(b) for _, b in rows]}
            try:
                r = self.session.post(f"{self.base}/v1/readings", json=payload, timeout=self.timeout)
            except requests.RequestException:
                return sent  # offline: keep everything
            if r.status_code == 201:
                self.db.execute("DELETE FROM queue WHERE id <= ?", (rows[-1][0],))
                self.db.commit()
                sent += len(rows)
            elif r.status_code in (401, 403):
                raise AuthError(r.text)
            elif r.status_code == 400:
                # A malformed batch would block the queue forever; drop it and report.
                self.db.execute("DELETE FROM queue WHERE id <= ?", (rows[-1][0],))
                self.db.commit()
                raise ValueError(f"server rejected a batch as invalid: {r.text}")
            else:
                return sent  # 429 / 5xx: retry later

    # ---- reading (customer or device key) ----
    def _get(self, path, params=None):
        r = self.session.get(f"{self.base}{path}", params=params, timeout=self.timeout)
        if r.status_code in (401, 403):
            raise AuthError(r.text)
        r.raise_for_status()
        return r.json()

    def devices(self):
        return self._get("/v1/devices")

    def latest(self, device_id):
        return self._get(f"/v1/devices/{device_id}/latest")

    def metrics(self, device_id, metric, interval="hour", start=None, end=None):
        params = {"metric": metric, "interval": interval}
        if start:
            params["from"] = start
        if end:
            params["to"] = end
        return self._get(f"/v1/devices/{device_id}/metrics", params)

    # ---- admin (admin key; run from your own backend or scripts only) ----
    def _post(self, path, body=None):
        r = self.session.post(f"{self.base}{path}", json=body, timeout=self.timeout)
        if r.status_code in (401, 403):
            raise AuthError(r.text)
        r.raise_for_status()
        return r.json()

    def create_customer(self, name):
        return self._post("/v1/admin/customers", {"name": name})

    def create_device(self, customer_id, name):
        """Returns {'device': {...}, 'api_key': '...'}; the key is shown only once."""
        return self._post(f"/v1/admin/customers/{customer_id}/devices", {"name": name})

    def create_customer_key(self, customer_id):
        return self._post(f"/v1/admin/customers/{customer_id}/keys")


if __name__ == "__main__":
    # Example machine agent. Set the key in the environment, never in the code:
    #   PowerShell:  $env:IOT_DEVICE_KEY = "iot_..."
    import os

    client = IoTClient(os.environ["IOT_DEVICE_KEY"])
    copies = 0
    while True:
        copies += 1  # replace with the real counter read from the machine
        client.record("copies_printed", copies)
        try:
            n = client.flush()
            if n:
                print(f"sent {n} readings")
        except AuthError as e:
            raise SystemExit(f"device key rejected, stopping: {e}")
        time.sleep(30)
