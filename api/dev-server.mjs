// Local API server for tests and demos: node dev-server.mjs [port]  (in-memory; MASTER_KEY random; WORKER_SECRET from env or "wk")
import http from 'node:http';
import { createApi, MemoryStore } from './src/index.js';
const port = Number(process.argv[2] || process.env.PORT || 8788);
const master = Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url');
const plans = process.env.PLANS ? JSON.parse(process.env.PLANS) : { pro: { accounts: 20, posts_month: 6000 } };
const api = createApi({ store: new MemoryStore(), env: { MASTER_KEY: master, WORKER_SECRET: process.env.WORKER_SECRET || 'wk' }, plans });
http.createServer(async (req, res) => {
  const chunks = []; for await (const c of req) chunks.push(c);
  const r = await api(new Request(`http://localhost:${port}${req.url}`, { method: req.method, headers: req.headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks) }));
  res.writeHead(r.status, Object.fromEntries(r.headers)); res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, () => console.log('READY ' + port));
