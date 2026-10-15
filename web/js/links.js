// Turns pasted text into link entries. The id rule is identical to worker/reelio/sources/links.py, so a link is never queued twice.
const IG = /instagram\.com\/(?:[\w.]+\/)?(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/i;
const YT = /(?:youtube\.com\/(?:shorts\/|watch\?(?:[^#]*&)?v=|embed\/|live\/)|youtu\.be\/)([A-Za-z0-9_-]{6,})/i;

async function sha1(s) {
  const b = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
}

export async function linkId(url) {
  let m = url.match(IG); if (m) return 'ig_' + m[1];
  m = url.match(YT); if (m) return 'yt_' + m[1];
  return 'u_' + (await sha1(url.toLowerCase().replace(/[?#].*$/, '').replace(/\/+$/, ''))).slice(0, 12);
}

/** One link per line. "link | my caption" sets a caption for that video. Returns [{id,url,caption}]. */
export async function parseLinks(text) {
  const out = [], seen = new Set();
  for (const line of String(text || '').split('\n')) {
    const m = line.match(/https?:\/\/[^\s|]+/); if (!m) continue;
    const url = m[0].replace(/[.,;]+$/, ''), id = await linkId(url);
    if (seen.has(id)) continue; seen.add(id);
    const cap = line.includes('|') ? line.slice(line.indexOf('|') + 1).trim() : '';
    out.push({ id, url, caption: cap });
  }
  return out;
}
