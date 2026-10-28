CREATE TABLE customers (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE devices (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz
);
CREATE INDEX devices_customer_idx ON devices(customer_id);

-- A key is scoped to one device (machines/agents sending data) or, when
-- device_id is NULL, to a whole customer (dashboards, mobile and desktop apps).
-- Only the SHA-256 of the key is stored; the plaintext is shown once at creation.
CREATE TABLE api_keys (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  device_id   uuid REFERENCES devices(id) ON DELETE CASCADE,
  key_hash    text NOT NULL UNIQUE,
  label       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at  timestamptz
);

CREATE TABLE readings (
  device_id   uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  metric      text NOT NULL,
  value       double precision NOT NULL,
  ts          timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX readings_lookup_idx ON readings(device_id, metric, ts DESC);
