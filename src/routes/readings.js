import { pool } from '../db.js';
import { requireKey } from '../auth.js';

const MAX_BATCH = 500;
const reading = {
  type: 'object',
  properties: {
    metric: { type: 'string', minLength: 1, maxLength: 100 },
    value: { type: 'number' },
    ts: { type: 'string', format: 'date-time' },
  },
  required: ['metric', 'value'],
  additionalProperties: false,
};
const uuidParam = { type: 'object', properties: { id: { type: 'string', format: 'uuid' } }, required: ['id'] };

// A device key may only see its own device; a customer key sees all of that customer's devices.
async function deviceAllowed(auth, deviceId) {
  if (auth.deviceId) return auth.deviceId === deviceId;
  const { rowCount } = await pool.query('SELECT 1 FROM devices WHERE id = $1 AND customer_id = $2', [
    deviceId,
    auth.customerId,
  ]);
  return rowCount > 0;
}

export default async function readingRoutes(app) {
  app.addHook('preHandler', requireKey);

  // Machines post here. Accepts one reading, or {"readings": [...]} for batches (e.g. after being offline).
  app.post(
    '/readings',
    {
      schema: {
        body: {
          oneOf: [
            reading,
            {
              type: 'object',
              properties: { readings: { type: 'array', minItems: 1, maxItems: MAX_BATCH, items: reading } },
              required: ['readings'],
              additionalProperties: false,
            },
          ],
        },
      },
    },
    async (req, reply) => {
      if (!req.auth.deviceId) return reply.code(403).send({ error: 'a device key is required to submit readings' });
      const items = req.body.readings ?? [req.body];
      const now = new Date().toISOString();
      await pool.query(
        `INSERT INTO readings (device_id, metric, value, ts)
         SELECT $1, m, v, t FROM unnest($2::text[], $3::float8[], $4::timestamptz[]) AS x(m, v, t)`,
        [req.auth.deviceId, items.map((r) => r.metric), items.map((r) => r.value), items.map((r) => r.ts ?? now)]
      );
      await pool.query('UPDATE devices SET last_seen = now() WHERE id = $1', [req.auth.deviceId]);
      return reply.code(201).send({ accepted: items.length });
    }
  );

  app.get('/devices', async (req) => {
    const { rows } = await pool.query(
      `SELECT id, name, created_at, last_seen FROM devices
       WHERE customer_id = $1 AND ($2::uuid IS NULL OR id = $2) ORDER BY name`,
      [req.auth.customerId, req.auth.deviceId]
    );
    return rows;
  });

  // Newest value per metric, e.g. for a live "copies printed" tile.
  app.get('/devices/:id/latest', { schema: { params: uuidParam } }, async (req, reply) => {
    if (!(await deviceAllowed(req.auth, req.params.id))) return reply.code(404).send({ error: 'device not found' });
    const { rows } = await pool.query(
      `SELECT DISTINCT ON (metric) metric, value, ts FROM readings WHERE device_id = $1 ORDER BY metric, ts DESC`,
      [req.params.id]
    );
    return rows;
  });

  // Time-bucketed aggregates for charts. Use sum for per-event deltas, max/last for running counters.
  app.get(
    '/devices/:id/metrics',
    {
      schema: {
        params: uuidParam,
        querystring: {
          type: 'object',
          properties: {
            metric: { type: 'string', minLength: 1 },
            from: { type: 'string', format: 'date-time' },
            to: { type: 'string', format: 'date-time' },
            interval: { type: 'string', enum: ['minute', 'hour', 'day', 'week', 'month'], default: 'hour' },
          },
          required: ['metric'],
        },
      },
    },
    async (req, reply) => {
      if (!(await deviceAllowed(req.auth, req.params.id))) return reply.code(404).send({ error: 'device not found' });
      const { metric, interval } = req.query;
      const to = req.query.to ?? new Date().toISOString();
      const from = req.query.from ?? new Date(Date.parse(to) - 24 * 3600 * 1000).toISOString();
      const { rows } = await pool.query(
        `SELECT date_trunc($4, ts) AS bucket, count(*)::int AS count, sum(value) AS sum,
                avg(value) AS avg, min(value) AS min, max(value) AS max,
                (array_agg(value ORDER BY ts DESC))[1] AS last
         FROM readings
         WHERE device_id = $1 AND metric = $2 AND ts >= $3 AND ts < $5
         GROUP BY bucket ORDER BY bucket`,
        [req.params.id, metric, from, interval, to]
      );
      return { metric, interval, from, to, buckets: rows };
    }
  );
}
