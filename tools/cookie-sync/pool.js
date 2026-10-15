// Same splitting rules as the Reelio app and worker (web/js/cookies.js, worker/reelio/cookiepool.py).
export const MARK = '# ---- next cookie ----';
const HEADER = /^\s*#\s*(Netscape\s+)?HTTP Cookie File/i;
const goodLine = (l) => l.trim() && (!l.trim().startsWith('#') || l.trim().startsWith('#HttpOnly_')) && l.replace(/[\r\n]+$/, '').split('\t').length >= 7;

export function splitCookies(text) {
  const chunks = []; let cur = [];
  for (const line of String(text || '').replace(/\r\n/g, '\n').split('\n')) {
    if (line.trim() === MARK || HEADER.test(line)) { if (cur.length) chunks.push(cur); cur = line.trim() === MARK ? [] : [line]; } else cur.push(line);
  }
  if (cur.length) chunks.push(cur);
  const seen = new Set(), out = [];
  for (const c of chunks) {
    if (!c.some(goodLine)) continue;
    const body = c.filter((l) => l.trim() && !HEADER.test(l)).join('\n'); if (seen.has(body)) continue; seen.add(body); out.push(c.join('\n'));
  }
  return out;
}

/** Put this browser profile's cookie into the list: replaces its own earlier export, never touches the others. */
export function mergeProfile(existingText, chunk, profileId) {
  const mine = new RegExp('^\\s*#\\s*reelio-profile:\\s*' + profileId + '(\\s|$)', 'm');
  const rest = splitCookies(existingText).filter((p) => !mine.test(p));
  return [...rest, chunk].join('\n' + MARK + '\n');
}
