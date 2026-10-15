// YouTube cookies, made simple: one place, as many cookies as you like, no "account" to make.
import { h, toast } from './core.js';
import { S as GS, saveCfg, saveSecret, readSecret } from './app.js';

const MARK = '# ---- next cookie ----';
const HEADER = /^\s*#\s*(Netscape\s+)?HTTP Cookie File/i;
const goodLine = (l) => l.trim() && (!l.trim().startsWith('#') || l.trim().startsWith('#HttpOnly_')) && l.replace(/[\r\n]+$/, '').split('\t').length >= 7;

/** Split pasted text (one file, many files, or a mix) into separate cookies. Same rules as the worker. */
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

const when = (iso) => { try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: GS.tz || undefined }); } catch { return ''; } };

/** A small status line for Accounts and the flow editor. */
export function cookieStatus(S, app) {
  let c = (S.status && S.status.cookies) || null;
  const saved = (S.cfg && S.cfg.cookie_count) || 0;
  if ((!c || !c.total) && saved) c = { total: saved, ready: saved, resting: 0, parked: 0, fresh: true };
  if (c && c.total && !saved && !(S.status.cookies && S.status.cookies.total)) c = null;
  let line;
  if (!c || !c.total) line = 'No cookies added. That is fine until YouTube blocks a download.';
  else {
    const bits = [`${c.ready} ready`];
    if (c.resting) bits.push(`${c.resting} resting${c.next_at ? ' (next back around ' + when(c.next_at) + ')' : ''}`);
    if (c.parked) bits.push(`${c.parked} logged out`);
    line = c.fresh ? `${c.total} cookie${c.total === 1 ? '' : 's'} saved. Reelio checks them on its next run.` : `${c.total} cookie${c.total === 1 ? '' : 's'}: ` + bits.join(', ') + '.';
  }
  const pill = !c || !c.total ? null : h('span', { class: 'pill ' + (c.ready ? 'ok' : 'warn') }, c.ready ? 'Working' : 'All resting');
  return h('div', { class: 'col' },
    h('div', { class: 'row' }, h('div', { class: 'grow small' }, line), pill),
    h('div', { class: 'row' }, h('button', { type: 'button', class: 'btn small primary', onclick: () => openCookieDialog(S, app) }, c && c.total ? 'Add more cookies' : 'Add cookies')),
    c && c.total ? h('div', { class: 'small muted' }, 'Reelio tries them one by one and rests the ones that fail. A rested cookie is used again by itself when its timer ends. If every cookie fails, it uses your backup Drive folder (if the flow has one) or waits for the soonest cookie.') : null);
}

export function openCookieDialog(S, app) {
  let pending = [];                                  // texts read from chosen files
  const info = h('div', { class: 'small muted', id: 'ck_info' }, 'Nothing chosen yet.');
  const ta = h('textarea', { id: 'ck_text', placeholder: 'Or paste cookie text here (one or many, it is split for you)', rows: 4 });
  const refresh = () => { const n = splitCookies([...pending, ta.value].join('\n' + MARK + '\n')).length; info.textContent = n ? `Ready to add: ${n} cookie${n === 1 ? '' : 's'}.` : 'Nothing chosen yet.'; };
  ta.addEventListener('input', refresh);
  const take = async (files) => { pending = pending.concat(await Promise.all([...files].map((f) => f.text()))); refresh(); };
  const pick = h('input', { type: 'file', multiple: true, accept: '.txt,text/plain', style: 'display:none', onchange: (e) => take(e.target.files) });
  const drop = h('div', { class: 'card', style: 'text-align:center;cursor:pointer;border-style:dashed', tabindex: '0', role: 'button', onclick: () => pick.click(), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') pick.click(); } }, h('b', null, 'Choose all your cookie files at once'), h('div', { class: 'small muted' }, 'or drop them here'));
  drop.addEventListener('dragover', (e) => e.preventDefault());
  drop.addEventListener('drop', (e) => { e.preventDefault(); take(e.dataTransfer.files); });
  const px = h('input', { type: 'text', id: 'ck_px', autocomplete: 'off', placeholder: 'http://user:pass@host:port' });
  const auto = h('div', { class: 'card col' },
    h('b', null, 'Best way: automatic (set up once)'),
    h('p', { class: 'small', style: 'margin:0' }, 'Install the Reelio Cookie Sync add-on in Chrome or Edge. After that it sends fresh cookies to Reelio by itself every hour. No more private windows, no more files.'),
    h('a', { class: 'btn small primary', href: 'downloads/reelio-cookie-sync.zip', download: 'reelio-cookie-sync.zip' }, 'Download the add-on'),
    h('ol', { class: 'steps' },
      h('li', null, h('div', null, 'Unzip the file you downloaded (right-click, Extract all).')),
      h('li', null, h('div', null, 'In Chrome type ', h('code', null, 'chrome://extensions'), ' in the address bar (Edge: ', h('code', null, 'edge://extensions'), '). Turn on ', h('b', null, 'Developer mode'), ' (top right). Click ', h('b', null, 'Load unpacked'), ' and choose the unzipped folder.')),
      h('li', null, h('div', null, 'In that same browser, sign in to YouTube once with a ', h('b', null, 'spare'), ' Google account.')),
      h('li', null, h('div', null, 'Come back to this Reelio page, click the puzzle-piece icon at the top of the browser, click ', h('b', null, 'Reelio Cookie Sync'), ', then ', h('b', null, 'Connect to Reelio'), '. Done.'))),
    h('p', { class: 'small muted', style: 'margin:0' }, 'More accounts: do steps 2 to 4 again in another Chrome profile (one profile per Google account). Works with the normal GitHub login, on a computer.'));
  const manual = h('details', null, h('summary', null, 'Or add cookie files by hand'),
    h('div', { class: 'col' },
      h('ol', { class: 'steps' },
        h('li', null, h('div', null, 'Open a ', h('b', null, 'private (incognito) window'), ' and sign in to YouTube with a ', h('b', null, 'spare'), ' Google account, not your main one.')),
        h('li', null, h('div', null, 'Click the extension ', h('b', null, 'Get cookies.txt LOCALLY'), ', press ', h('b', null, 'Export'), ', then close the private window.')),
        h('li', null, h('div', null, 'Do that for each account, then choose all the files below in one go.'))),
      drop, pick, ta, info));
  const body = h('div', { class: 'col' },
    h('p', null, 'Only needed if YouTube says it is blocking downloads. Reelio tries your cookies one by one, rests the ones that stop working, and uses them again when they recover.'),
    auto, manual,
    h('p', { class: 'small muted' }, 'Cookies are like passwords: they are locked with your passphrase and never shown again. YouTube can limit an account that is used for downloads, so use spare accounts.'),
    h('details', null, h('summary', null, 'Advanced: proxy (optional)'), h('label', { class: 'f' }, 'Proxy address', px)));
  const d = h('dialog', null, h('div', { class: 'body' }, h('h2', null, 'YouTube cookies'), body, h('div', { class: 'row' },
    h('button', { class: 'btn primary', onclick: async () => {
      const fresh = splitCookies([...pending, ta.value].join('\n' + MARK + '\n')), proxy = px.value.trim();
      if (!fresh.length && !proxy) return toast('Choose or paste at least one cookie file.');
      try {
        const old = await readSecret('youtube-net').catch(() => ({}));
        const all = splitCookies([old.cookies || '', ...fresh].join('\n' + MARK + '\n'));
        await saveSecret('youtube-net', { cookies: all.join('\n' + MARK + '\n'), proxy: proxy || old.proxy || '' });
        await saveCfg((c) => { if (!c.connections.some((x) => x.id === 'youtube-net')) c.connections.push({ id: 'youtube-net', kind: 'ytnet', label: 'YouTube cookies' }); c.cookie_count = all.length; }, 'Reelio: saved YouTube cookies');
        d.close(); d.remove(); toast(`Saved. Reelio now has ${all.length} cookie${all.length === 1 ? '' : 's'}.`, 6000); if (app && app.rerender) app.rerender();
      } catch (e) { toast(e.message, 8000); }
    } }, 'Add'),
    h('button', { class: 'btn', onclick: () => { d.close(); d.remove(); } }, 'Cancel'),
    h('button', { class: 'btn small danger right', onclick: async () => {
      if (!confirm('Remove ALL saved YouTube cookies?')) return;
      try { await saveSecret('youtube-net', { cookies: '' }); await saveCfg((c) => { c.cookie_count = 0; }, 'Reelio: removed YouTube cookies'); d.close(); d.remove(); toast('Removed.'); if (app && app.rerender) app.rerender(); } catch (e) { toast(e.message, 8000); }
    } }, 'Remove all'))));
  d.addEventListener('cancel', () => d.remove()); document.body.append(d); d.showModal(); return d;
}
