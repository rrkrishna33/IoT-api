import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import pg from 'pg';

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'migrations');
const client = new pg.Client({ connectionString: process.env.DATABASE_URL });
await client.connect();

await client.query(
  'CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())'
);
const done = new Set((await client.query('SELECT name FROM schema_migrations')).rows.map((r) => r.name));

for (const file of (await readdir(dir)).filter((f) => f.endsWith('.sql')).sort()) {
  if (done.has(file)) continue;
  console.log('applying', file);
  try {
    await client.query('BEGIN');
    await client.query(await readFile(path.join(dir, file), 'utf8'));
    await client.query('INSERT INTO schema_migrations(name) VALUES ($1)', [file]);
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('failed:', err.message);
    process.exitCode = 1;
    break;
  }
}
await client.end();
