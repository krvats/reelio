// AES-256-GCM + PBKDF2-SHA256 (200k): the exact format the Reelio app and worker use for secrets.enc.json.
const enc = new TextEncoder(), dec = new TextDecoder();
export const b64 = (buf) => { const a = new Uint8Array(buf); let s = ''; for (let i = 0; i < a.length; i += 8192) s += String.fromCharCode(...a.subarray(i, i + 8192)); return btoa(s); };
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function deriveKey(pass, salt, iter) {
  const km = await crypto.subtle.importKey('raw', enc.encode(pass), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: iter, hash: 'SHA-256' }, km, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}
export async function encryptJson(obj, pass, iter = 200000) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await deriveKey(pass, salt, iter), enc.encode(JSON.stringify(obj)));
  return { v: 1, kdf: 'pbkdf2-sha256', iter, salt: b64(salt), iv: b64(iv), ct: b64(ct) };
}
export async function decryptJson(blob, pass) {
  try {
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(blob.iv) }, await deriveKey(pass, unb64(blob.salt), blob.iter || 200000), unb64(blob.ct));
    return JSON.parse(dec.decode(pt));
  } catch { throw new Error('The Reelio passphrase did not unlock your saved logins. Open the Reelio app, then press Connect again.'); }
}
