// Local server for development and cross-language tests: node scripts/dev-server.mjs  (in-memory; prints the port; keys are throwaway)
import http from 'node:http';
import { createApi, MemoryStore } from '../src/index.js';
const env = { MASTER_KEY: Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url'), WORKER_SECRET: process.env.WORKER_SECRET || 'dev-worker', ADMIN_SECRET: 'dev-admin' };
const api = createApi({ store: new MemoryStore(), env, plans: { pro: { accounts: 10, posts_month: 6000 } } });
const srv = http.createServer(async (req, res) => {
  const chunks = []; for await (const c of req) chunks.push(c);
  const r = await api(new Request(`http://localhost${req.url}`, { method: req.method, headers: req.headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks) }));
  res.writeHead(r.status, Object.fromEntries(r.headers)); res.end(Buffer.from(await r.arrayBuffer()));
}).listen(Number(process.env.PORT || 0), '127.0.0.1', () => console.log('READY ' + srv.address().port));
