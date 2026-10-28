import { pool } from '../db.js';
import { hashKey, newKey, requireAdmin } from '../auth.js';

const uuidParam = { type: 'object', properties: { id: { type: 'string', format: 'uuid' } }, required: ['id'] };
const nameBody = {
  type: 'object',
  properties: { name: { type: 'string', minLength: 1, maxLength: 200 } },
  required: ['name'],
  additionalProperties: false,
};

async function issueKey(customerId, deviceId, label) {
  const key = newKey();
  await pool.query(
    'INSERT INTO api_keys (customer_id, device_id, key_hash, label) VALUES ($1, $2, $3, $4)',
    [customerId, deviceId, hashKey(key), label ?? null]
  );
  return key;
}

export default async function adminRoutes(app) {
  app.addHook('preHandler', requireAdmin);

  app.post('/customers', { schema: { body: nameBody } }, async (req, reply) => {
    const { rows } = await pool.query('INSERT INTO customers (name) VALUES ($1) RETURNING *', [req.body.name]);
    return reply.code(201).send(rows[0]);
  });

  // Customer-wide key, for dashboards and mobile/desktop apps (read access to all the customer's devices).
  app.post('/customers/:id/keys', { schema: { params: uuidParam } }, async (req, reply) => {
    const { rowCount } = await pool.query('SELECT 1 FROM customers WHERE id = $1', [req.params.id]);
    if (!rowCount) return reply.code(404).send({ error: 'customer not found' });
    const api_key = await issueKey(req.params.id, null, 'customer');
    return reply.code(201).send({ api_key, note: 'store this now; it cannot be shown again' });
  });

  // Registers a machine and returns its device key.
  app.post('/customers/:id/devices', { schema: { params: uuidParam, body: nameBody } }, async (req, reply) => {
    const { rowCount } = await pool.query('SELECT 1 FROM customers WHERE id = $1', [req.params.id]);
    if (!rowCount) return reply.code(404).send({ error: 'customer not found' });
    const { rows } = await pool.query(
      'INSERT INTO devices (customer_id, name) VALUES ($1, $2) RETURNING *',
      [req.params.id, req.body.name]
    );
    const api_key = await issueKey(req.params.id, rows[0].id, req.body.name);
    return reply.code(201).send({ device: rows[0], api_key, note: 'store this now; it cannot be shown again' });
  });

  app.delete('/keys/:id', { schema: { params: uuidParam } }, async (req, reply) => {
    const { rowCount } = await pool.query(
      'UPDATE api_keys SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL',
      [req.params.id]
    );
    return rowCount ? { revoked: true } : reply.code(404).send({ error: 'key not found or already revoked' });
  });
}
