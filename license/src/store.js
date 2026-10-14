// Storage adapters. The service only needs get/put/del; swap in Cloudflare KV (or D1 later) without touching the logic.
export class MemoryStore {
  constructor() { this.m = new Map(); }
  async get(k) { const e = this.m.get(k); if (!e) return null; if (e.exp && e.exp < Date.now()) { this.m.delete(k); return null; } return structuredClone(e.v); }
  async put(k, v, { ttl } = {}) { this.m.set(k, { v: structuredClone(v), exp: ttl ? Date.now() + ttl * 1000 : 0 }); }
  async del(k) { this.m.delete(k); }
  async keys(prefix) { return [...this.m.keys()].filter((k) => k.startsWith(prefix)); }
}
export class KVStore {   // Cloudflare KV namespace binding
  constructor(kv) { this.kv = kv; }
  async get(k) { const v = await this.kv.get(k); return v ? JSON.parse(v) : null; }
  async put(k, v, { ttl } = {}) { await this.kv.put(k, JSON.stringify(v), ttl ? { expirationTtl: Math.max(60, ttl) } : undefined); }
  async del(k) { await this.kv.delete(k); }
  async keys(prefix) { const r = await this.kv.list({ prefix }); return r.keys.map((x) => x.name); }
}
