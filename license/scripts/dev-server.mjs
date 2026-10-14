// Local test server: node scripts/dev-server.mjs  (in-memory, throwaway keys, admin secret "dev")
import http from 'node:http';
import { createApp } from '../src/index.js';
import { MemoryStore } from '../src/store.js';
const kp = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
const env = { SIGNING_KEY_JWK: await crypto.subtle.exportKey('jwk', kp.privateKey), ADMIN_SECRET: 'dev' };
const app = createApp({ store: new MemoryStore(), env });
const port = Number(process.env.PORT || 8787);
http.createServer(async (req, res) => {
  const chunks = []; for await (const c of req) chunks.push(c);
  const r = await app(new Request(`http://localhost:${port}${req.url}`, { method: req.method, headers: req.headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks) }));
  res.writeHead(r.status, Object.fromEntries(r.headers)); res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, () => console.log(`license dev server on :${port}`));
