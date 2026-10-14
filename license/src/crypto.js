// WebCrypto helpers shared by Cloudflare Workers and Node 20+.
const enc = new TextEncoder(), dec = new TextDecoder();
export const b64u = (buf) => { const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf); let s = ''; for (const c of b) s += String.fromCharCode(c); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
export const unb64u = (s) => { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; return Uint8Array.from(atob(s), (c) => c.charCodeAt(0)); };
export const utf8 = (s) => enc.encode(s);
export const text = (b) => dec.decode(b);
export const randomId = (n = 16) => b64u(crypto.getRandomValues(new Uint8Array(n)));
export const randomCode = () => { const A = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; const r = crypto.getRandomValues(new Uint8Array(8)); return [...r].map((x) => A[x % A.length]).join(''); };
export async function sha256(s) { return b64u(await crypto.subtle.digest('SHA-256', typeof s === 'string' ? enc.encode(s) : s)); }

/** A device is identified by the thumbprint of its public key (RFC 7638 style for EC keys). */
export async function deviceIdFromJwk(jwk) {
  if (!jwk || jwk.kty !== 'EC' || jwk.crv !== 'P-256' || !jwk.x || !jwk.y) throw new Error('bad device key');
  return sha256(`{"crv":"P-256","kty":"EC","x":"${jwk.x}","y":"${jwk.y}"}`);
}
export async function verifyDeviceSig(jwk, message, sigB64u) {
  try {
    const key = await crypto.subtle.importKey('jwk', { kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y, ext: true }, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    return await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, unb64u(sigB64u), enc.encode(message));
  } catch { return false; }
}

// ---- Ed25519 signed tokens (compact JWS, alg EdDSA). The public key is published; anyone can verify offline.
export async function importSigner(privateJwk) {
  return crypto.subtle.importKey('jwk', privateJwk, { name: 'Ed25519' }, false, ['sign']);
}
export async function signToken(privateKey, kid, claims) {
  const head = b64u(enc.encode(JSON.stringify({ alg: 'EdDSA', typ: 'JWT', kid })));
  const body = b64u(enc.encode(JSON.stringify(claims)));
  const sig = await crypto.subtle.sign({ name: 'Ed25519' }, privateKey, enc.encode(`${head}.${body}`));
  return `${head}.${body}.${b64u(sig)}`;
}
export async function verifyToken(publicXb64u, token, nowSec = Math.floor(Date.now() / 1000)) {
  const [h, b, s] = String(token).split('.');
  if (!h || !b || !s) throw new Error('malformed token');
  const key = await crypto.subtle.importKey('jwk', { kty: 'OKP', crv: 'Ed25519', x: publicXb64u }, { name: 'Ed25519' }, false, ['verify']);
  if (!(await crypto.subtle.verify({ name: 'Ed25519' }, key, unb64u(s), enc.encode(`${h}.${b}`)))) throw new Error('bad signature');
  const claims = JSON.parse(text(unb64u(b)));
  if (claims.exp && claims.exp < nowSec) throw new Error('token expired');
  return claims;
}

export async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return [...new Uint8Array(await crypto.subtle.sign('HMAC', key, enc.encode(message)))].map((x) => x.toString(16).padStart(2, '0')).join('');
}
export function safeEqual(a, b) {
  a = String(a); b = String(b); let r = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) r |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return r === 0;
}
