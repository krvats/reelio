// Runs the extension's real sync code against a fake Chrome and a fake GitHub, then writes the resulting data files
// to the folder given as argv[2] so the Python worker can open them (see worker/tests/test_cookiesync.py).
import fs from 'node:fs'; import path from 'node:path'; import assert from 'node:assert/strict';
import { encryptJson, decryptJson } from '../crypto.js';

const PASS = 'test-passphrase', files = new Map();
const put = (p, obj) => files.set(p, { sha: Math.random().toString(36).slice(2), text: JSON.stringify(obj, null, 1) });
put('secrets.enc.json', await encryptJson({ 'ig_1': { access_token: 'IGTOKEN' } }, PASS));
put('config.json', { connections: [], routes: [] });

globalThis.fetch = async (url, o = {}) => {
  const p = decodeURIComponent(new URL(url).pathname.replace(/^\/repos\/[^/]+\/[^/]+\/contents\//, ''));
  const json = (code, b) => ({ status: code, ok: code < 400, json: async () => b });
  if ((o.method || 'GET') === 'GET') { const f = files.get(p); return f ? json(200, { sha: f.sha, content: Buffer.from(f.text).toString('base64') }) : json(404, {}); }
  const b = JSON.parse(o.body), f = files.get(p);
  if (f && b.sha !== f.sha) return json(409, {});
  files.set(p, { sha: Math.random().toString(36).slice(2), text: Buffer.from(b.content, 'base64').toString() });
  return json(200, {});
};
let browser = [];
const mem = {};
globalThis.chrome = { storage: { local: { get: async () => ({ ...mem }), set: async (o) => { Object.assign(mem, o); }, clear: async () => { for (const k in mem) delete mem[k]; } } },
  cookies: { getAll: async ({ domain }) => browser.filter((c) => c.domain.endsWith(domain)) } };
const { syncNow } = await import('../sync.js');
const ck = (domain, name, value, extra = {}) => ({ domain, path: '/', name, value, secure: true, httpOnly: false, expirationDate: 2000000000, ...extra });
const login = (tag) => [ck('.youtube.com', 'VISITOR_INFO1_LIVE', 'v' + tag), ck('.google.com', 'SAPISID', 'S' + tag, { httpOnly: true }), ck('.google.com', 'NID', 'n' + tag, { expirationDate: undefined })];
const secrets = async () => (await decryptJson(JSON.parse(files.get('secrets.enc.json').text), PASS));
const base = { token: 't', pass: PASS, owner: 'krvats', data: 'reelio-data', api: 'https://api.github.com' };

browser = []; Object.assign(mem, base, { profileId: 'aaaa11', label: 'Spare 1' });
assert.equal((await syncNow()).ok, false, 'not signed in must not send anything');

browser = login('A1'); assert.equal((await syncNow()).ok, true);
Object.assign(mem, { profileId: 'bbbb22', label: 'Spare 2', lastHash: null }); browser = login('B1'); assert.equal((await syncNow()).ok, true);
let s = await secrets(); assert.equal(s.ig_1.access_token, 'IGTOKEN', 'other logins must survive');
assert.equal(s['youtube-net'].cookies.split('# ---- next cookie ----').length, 2);
assert.equal(JSON.parse(files.get('config.json').text).cookie_count, 2);
Object.assign(mem, { profileId: 'aaaa11', label: 'Spare 1', lastHash: null }); browser = login('A2'); assert.equal((await syncNow()).ok, true);
s = await secrets(); const t = s['youtube-net'].cookies;
assert.equal(t.split('# ---- next cookie ----').length, 2, 'a refresh replaces the same browser, never adds a duplicate');
assert.ok(t.includes('SA2') && !t.includes('SA1') && t.includes('SB1'));
assert.ok(t.includes('#HttpOnly_.google.com\tTRUE\t/\tTRUE\t2000000000\tSAPISID\tSA2'));
assert.equal((await syncNow()).msg, 'Already up to date.');
for (const [n, f] of files) { const d = path.join(process.argv[2] || '/tmp', n); fs.mkdirSync(path.dirname(d), { recursive: true }); fs.writeFileSync(d, f.text); }
console.log('extension sync ok');
