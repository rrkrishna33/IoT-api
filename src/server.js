import Fastify from 'fastify';
import helmet from '@fastify/helmet';
import cors from '@fastify/cors';
import rateLimit from '@fastify/rate-limit';
import { pool } from './db.js';
import adminRoutes from './routes/admin.js';
import readingRoutes from './routes/readings.js';

for (const name of ['DATABASE_URL', 'ADMIN_KEY']) {
  if (!process.env[name]) {
    console.error(`${name} is not set`);
    process.exit(1);
  }
}

// Behind Caddy (and Cloudflare), so trust the forwarded client IP for rate limiting.
const app = Fastify({ logger: true, trustProxy: true, bodyLimit: 1_000_000 });

await app.register(helmet);
await app.register(cors, {
  origin: (process.env.CORS_ORIGINS ?? '').split(',').map((s) => s.trim()).filter(Boolean),
});
await app.register(rateLimit, { max: 300, timeWindow: '1 minute' });

app.get('/health', async () => {
  await pool.query('SELECT 1');
  return { ok: true };
});

await app.register(adminRoutes, { prefix: '/v1/admin' });
await app.register(readingRoutes, { prefix: '/v1' });

const close = async () => {
  await app.close();
  await pool.end();
  process.exit(0);
};
process.on('SIGTERM', close);
process.on('SIGINT', close);

await app.listen({ port: Number(process.env.PORT ?? 4000), host: process.env.HOST ?? '127.0.0.1' });
