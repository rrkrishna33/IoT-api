import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { pool } from './db.js';

export const hashKey = (key) => createHash('sha256').update(key).digest('hex');
export const newKey = () => `iot_${randomBytes(32).toString('base64url')}`;

const keyFrom = (req) => {
  const header = req.headers['x-api-key'];
  if (header) return header;
  const m = /^Bearer (.+)$/.exec(req.headers.authorization ?? '');
  return m ? m[1] : null;
};

// preHandler for /v1/admin/*: compares against ADMIN_KEY in constant time.
export async function requireAdmin(req, reply) {
  const given = Buffer.from(hashKey(keyFrom(req) ?? ''));
  const expected = Buffer.from(hashKey(process.env.ADMIN_KEY ?? ''));
  if (!process.env.ADMIN_KEY || !timingSafeEqual(given, expected)) {
    return reply.code(401).send({ error: 'invalid admin key' });
  }
}

// preHandler for device/customer keys. Sets req.auth = { customerId, deviceId|null }.
export async function requireKey(req, reply) {
  const key = keyFrom(req);
  if (!key) return reply.code(401).send({ error: 'missing API key' });
  const { rows } = await pool.query(
    'SELECT customer_id, device_id FROM api_keys WHERE key_hash = $1 AND revoked_at IS NULL',
    [hashKey(key)]
  );
  if (!rows.length) return reply.code(401).send({ error: 'invalid API key' });
  req.auth = { customerId: rows[0].customer_id, deviceId: rows[0].device_id };
}
