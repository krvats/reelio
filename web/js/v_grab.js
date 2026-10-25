// Save to Drive: paste a YouTube / Instagram link (video, playlist or channel) and the cloud worker saves it into your Google Drive as mp4.
// Playlists get their own sub-folder. "My Instagram" saves every video of one of your connected Instagram accounts (official API).
import { h, icon, toast, ago, uid, fmtTime, LS } from './core.js';

const PILL = { queued: ['Waiting', ''], running: ['Working', 'warn'], done: ['Saved', 'ok'], failed: ['Needs attention', 'bad'], cancelled: ['Stopped', ''] };
const ITEM = { pending: 'Waiting', downloading: 'Downloading', uploading: 'Saving to Drive', done: 'Saved', failed: 'Failed' };
const RUNNING = new Set(['queued', 'in_progress', 'waiting', 'pending', 'requested']);
const LOCAL = [];          // requests added from this screen: { id, label, at, stage: 'saving' | 'saved' | 'waiting' | 'read' | 'error', path, note }
let defaultRef = null;
const spin = () => h('span', { class: 'spinner', 'aria-hidden': 'true' });
const bytes = (n) => (n > 1e9 ? (n / 1e9).toFixed(1) + ' GB' : (n / 1e6).toFixed(0) + ' MB');

async function loadInbox(S) {
  if (typeof S.data.list !== 'function') return null;
  const files = (await S.data.list('grab-inbox')).filter((f) => f.name && f.name.endsWith('.json'));
  return Promise.all(files.slice(0, 8).map(async (f) => ({ name: f.name, cmd: (await S.data.read('grab-inbox/' + f.name).catch(() => null)) || {} })));
}

async function latestRun(S) {
  const res = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}/actions/workflows/grab.yml/runs?per_page=1`, { cache: 'no-store' });
  if (!res.ok) return null;
  return ((await res.json()).workflow_runs || [])[0] || null;
}

async function loadJobs(S) {
  const res = await S.data.gh(S.data.base() + 'queues/grab', { cache: 'no-store' });
  if (res.status === 404) return { jobs: [], state: {} };
  if (!res.ok) throw new Error(`Could not read the Save to Drive list (${res.status}).`);
  const files = (await res.json()).filter((f) => f.name.endsWith('.json'));
  const state = (await S.data.read('queues/grab/_state.json')) || {};
  const jobs = (await Promise.all(files.filter((f) => !f.name.startsWith('_')).slice(0, 30).map((f) => S.data.read('queues/grab/' + f.name)))).filter((j) => j && j.items);
  jobs.sort((a, b) => (b.created || '').localeCompare(a.created || ''));
  return { jobs, state };
}

async function startWorker(S) {
  if (!defaultRef) { try { const r = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}`); defaultRef = r.ok ? (await r.json()).default_branch || 'main' : 'main'; } catch { defaultRef = 'main'; } }
  const res = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}/actions/workflows/grab.yml/dispatches`, { method: 'POST', body: JSON.stringify({ ref: defaultRef }) });
  if (res.status === 404) throw new Error('grab.yml was not found in your app repository. Add the file .github/workflows/grab.yml first.');
  if (res.status === 403 || res.status === 401) throw new Error('Your GitHub key is not allowed to start runs. It needs the "Actions: read and write" permission.');
  if (!res.ok) throw new Error(`GitHub could not start the run (${res.status}). Is the workflow enabled in the Actions tab?`);
}

async function send(S, cmd) {
  const path = `grab-inbox/${Date.now()}-${uid()}.json`;
  await S.data.put(path, cmd, 'Reelio save to Drive: ' + cmd.cmd);
  return path;
}

const describe = (c) => (c.cmd === 'add_ig' ? 'your Instagram videos' : `${(c.links || []).length || 1} link${(c.links || []).length === 1 ? '' : 's'}`);

export async function grabView(S, params, app) {
  if (typeof S.data.list !== 'function') {
    return h('div', { class: 'card col' }, h('h1', null, 'Save to Drive'), h('p', null, 'Save to Drive works in the normal GitHub mode. This copy of Reelio is running in hosted mode, where it is not available yet.'));
  }
  const [inbox, lrun] = await Promise.all([loadInbox(S).catch(() => null), latestRun(S).catch(() => null)]);
  let data;
  try { data = await loadJobs(S); } catch (e) { return h('div', { class: 'card' }, h('h1', null, 'Save to Drive'), h('p', null, e.message), h('button', { class: 'btn', onclick: () => app.rerender() }, 'Try again')); }
  const { jobs, state } = data;
  const googles = (S.cfg.connections || []).filter((c) => c.kind === 'google');
  const instas = (S.cfg.connections || []).filter((c) => c.kind === 'instagram');
  const saved = LS.get('grab.form', {});
  const f = { mode: 'links', links: '', ig: (instas[0] || {}).id || '', conn: (googles.find((g) => g.drive_write) || googles[0] || {}).id || 'google',
    quality: saved.quality || '1080', root_name: saved.root_name || 'Reelio Downloads', subfolders: saved.subfolders !== false, subs: !!saved.subs };
  const needPerm = !googles.length || !googles.some((g) => g.drive_write);

  const field = (label, input, hint) => h('label', { class: 'col', style: 'gap:4px' }, h('b', null, label), input, hint ? h('span', { class: 'small muted' }, hint) : null);
  const sel = (key, opts) => h('select', { onchange: (e) => { f[key] = e.target.value; if (key === 'mode') draw(); } }, opts.map(([v, l]) => h('option', { value: v, selected: String(f[key]) === String(v) }, l)));
  const modeBox = h('div', { class: 'col' });
  function draw() {
    modeBox.replaceChildren(...(f.mode === 'links'
      ? [field('Links', h('textarea', { rows: 4, placeholder: 'https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/playlist?list=...', 'aria-label': 'Links', oninput: (e) => { f.links = e.target.value; } }, f.links),
        'One per line. A video, a playlist or a channel from YouTube, or an Instagram post. Playlists go into their own folder.')]
      : [instas.length
        ? field('Instagram account', sel('ig', instas.map((c) => [c.id, c.label])), 'Saves every video from this account. Uses the official Instagram connection you already made, so no password or cookies are needed. Run it again later to pick up new videos.')
        : h('div', { class: 'banner warn' }, h('div', null, 'Connect an Instagram account first in ', h('a', { href: '#/accounts' }, 'Accounts'), '.'))]));
  }
  draw();

  const goLabel = [icon('play'), 'Save to Drive'];
  const go = h('button', { class: 'btn primary', onclick: async (e) => {
    const btn = e.currentTarget;
    const links = f.links.split(/\s+/).map((x) => x.trim()).filter(Boolean);
    if (f.mode === 'links' && !links.length) return toast('Paste at least one link.', 5000);
    if (f.mode === 'ig' && !f.ig) return toast('Pick an Instagram account.', 5000);
    if (!googles.length) return toast('Connect Google first in Accounts.', 5000);
    LS.set('grab.form', { quality: f.quality, root_name: f.root_name, subfolders: f.subfolders, subs: f.subs });
    const settings = { conn: f.conn, quality: f.quality, root_name: f.root_name.trim() || 'Reelio Downloads', subfolders: f.subfolders, subs: f.subs };
    const cmd = f.mode === 'links' ? { cmd: 'add', links, settings } : { cmd: 'add_ig', conn: f.ig, settings };
    btn.disabled = true; btn.replaceChildren(spin(), ' Adding...');
    const me = { id: uid(), label: describe(cmd), at: Date.now(), stage: 'saving' };
    LOCAL.unshift(me); drawPending();
    pendingBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
    try {
      me.path = await send(S, cmd); me.stage = 'saved'; drawPending();
      try { await startWorker(S); me.stage = 'waiting'; me.note = ''; toast('Added. The cloud worker is starting.', 4000); }
      catch (err) { me.stage = 'waiting'; me.note = `Saved, but the worker could not be started right now: ${err.message} It will still pick this up by itself within the hour.`; toast('Saved. ' + err.message, 8000); }
      drawPending(); f.links = ''; draw();
      setTimeout(() => app.rerender(), 5000);
    } catch (err) {
      me.stage = 'error'; me.note = err.message; drawPending(); toast(err.message, 7000);
    } finally { btn.disabled = false; btn.replaceChildren(...goLabel); }
  } }, goLabel);

  const permBanner = needPerm
    ? h('div', { class: 'banner warn' }, h('div', { class: 'grow' }, h('b', null, 'One-time step: let Reelio save into your Drive. '),
      h('div', { class: 'small' }, 'Your Google login can only read Drive today. Open Accounts, tap Google, then Reconnect. The consent screen will now also ask for "see and create files this app made". Your flows keep working exactly as before.'),
      h('a', { class: 'btn small', href: '#/accounts', style: 'margin-top:6px' }, 'Open Accounts')))
    : null;

  const adder = h('div', { class: 'card col' }, h('h2', { style: 'margin:0' }, 'Save videos to your Drive'),
    h('p', { class: 'muted', style: 'margin:0' }, 'Paste a link and tap the button. The cloud worker downloads it as an mp4 with the title, description, date and thumbnail inside the file, and puts it in your Drive. Your phone and computer can be off. Only save videos you own or have permission to keep.'),
    field('What to save', sel('mode', [['links', 'Links (YouTube or Instagram)'], ['ig', 'My Instagram account']])), modeBox,
    h('div', { class: 'grid' },
      field('Quality', sel('quality', [['480', '480p (smallest)'], ['720', '720p'], ['1080', '1080p (recommended)'], ['best', 'Best available (can be very large)']])),
      field('Main folder in Drive', h('input', { type: 'text', value: f.root_name, oninput: (e) => { f.root_name = e.target.value; } }), 'Reelio makes it for you the first time. You can rename or move it later.')),
    h('label', { class: 'row', style: 'gap:8px;align-items:center' }, h('input', { type: 'checkbox', checked: f.subfolders, onchange: (e) => { f.subfolders = e.target.checked; } }), h('span', null, 'Put playlists and channels in their own sub-folder')),
    h('label', { class: 'row', style: 'gap:8px;align-items:center' }, h('input', { type: 'checkbox', checked: f.subs, onchange: (e) => { f.subs = e.target.checked; } }), h('span', null, 'Also write English subtitles into the file (when the video has them)')),
    googles.length > 1 ? field('Save into this Google account', h('select', { onchange: (e) => { f.conn = e.target.value; } }, googles.map((c) => h('option', { value: c.id, selected: c.id === f.conn }, c.label + (c.drive_write ? '' : ' (needs reconnect)'))))) : null,
    h('div', { class: 'row' }, go),
    h('p', { class: 'small muted', style: 'margin:0' }, 'Reelio can only use folders it made itself. YouTube sometimes blocks cloud servers: if so, Reelio uses your saved cookies (Accounts > YouTube downloads) and waits by itself. Instagram links outside your own account usually need Instagram cookies and can put that account at risk, so prefer "My Instagram account".'));

  const until = (s) => (s && new Date(s) > new Date() ? new Date(s) : null);
  const waits = [...Object.values(state.source_until || {}).map(until), ...Object.values(state.conn_until || {}).map(until)].filter(Boolean);
  const paused = waits.length ? h('div', { class: 'banner warn' }, h('div', null, h('b', null, 'Paused for now. '),
    `Saving waits until about ${fmtTime(new Date(Math.max(...waits)).toISOString(), S.tz)} (YouTube or Instagram blocked the download, or Google asked to slow down). It continues by itself.`)) : null;

  const rootId = Object.entries(state.folders || {}).find(([k]) => !k.split('|')[2])?.[1];
  const folderLink = rootId ? h('a', { class: 'btn small', href: `https://drive.google.com/drive/folders/${rootId}`, target: '_blank', rel: 'noopener' }, 'Open main folder in Drive') : null;

  const jobCard = (j) => {
    const total = j.items.length, done = j.items.filter((i) => i.status === 'done').length, [label, cls] = PILL[j.status] || ['', ''];
    const failed = j.items.some((i) => i.status === 'failed');
    const act = async (cmd, msg) => { try { await send(S, { cmd, id: j.id }); await startWorker(S).catch(() => {}); toast(msg, 4000); setTimeout(() => app.rerender(), 3500); } catch (e) { toast(e.message, 6000); } };
    const order = { failed: 0, uploading: 1, downloading: 1, pending: 2, done: 3 };
    const rows = j.items.slice().sort((a, b) => (order[a.status] - order[b.status]) || (a.n - b.n)).slice(0, 200);
    const total_bytes = j.items.reduce((s, i) => s + (i.size || 0), 0);
    return h('div', { class: 'card col' },
      h('div', { class: 'row' }, h('h2', { class: 'grow', style: 'margin:0;word-break:break-word' }, j.title || j.id), h('span', { class: 'pill ' + cls }, label)),
      h('p', { class: 'muted', style: 'margin:0' }, `${done} of ${total} saved${j.folder ? ` in the folder "${j.folder}"` : ''}${total_bytes ? ` (${bytes(total_bytes)})` : ''}.`),
      h('div', { style: 'height:8px;border-radius:99px;background:var(--line);overflow:hidden', role: 'progressbar', 'aria-valuenow': done, 'aria-valuemax': total },
        h('div', { style: `height:100%;width:${Math.round(done / Math.max(1, total) * 100)}%;background:var(--brand)` })),
      total > 1 || failed ? h('details', null, h('summary', null, 'Show each video'),
        h('div', { class: 'col', style: 'gap:6px;margin-top:8px' }, rows.map((i) => h('div', { class: 'row gap-s', style: 'align-items:flex-start' },
          h('span', { class: 'pill ' + (i.status === 'done' ? 'ok' : i.status === 'failed' ? 'bad' : i.status === 'pending' ? '' : 'warn'), style: 'min-width:92px;justify-content:center' }, ITEM[i.status] || i.status),
          h('div', { class: 'grow small', style: 'word-break:break-word' }, i.title || i.vid, ' ', i.url_drive ? h('a', { href: i.url_drive, target: '_blank', rel: 'noopener' }, 'Open in Drive') : null,
            i.last_error && i.status !== 'done' ? h('div', { class: 'muted' }, i.last_error.msg + ' ' + (i.last_error.fix || '')) : null))),
        j.items.length > rows.length ? h('div', { class: 'small muted' }, `and ${j.items.length - rows.length} more`) : null)) : null,
      h('div', { class: 'row gap-s' },
        failed ? h('button', { class: 'btn small', onclick: () => act('retry', 'Trying the failed videos again.') }, icon('refresh'), 'Try failed videos again') : null,
        !['done', 'cancelled'].includes(j.status) ? h('button', { class: 'btn small', onclick: () => act('cancel', 'Stopped. Videos already in Drive stay there.') }, 'Stop') : null,
        ['done', 'cancelled', 'failed'].includes(j.status) ? h('button', { class: 'btn small danger', onclick: () => act('remove', 'Removed from this list. Files in Drive stay.') }, 'Remove from list') : null),
      h('p', { class: 'small muted', style: 'margin:0' }, `Updated ${ago(j.updated)}.${j.kind !== 'yt' || j.folder ? ' To pick up new videos later, add the same link (or account) again.' : ''}`));
  };

  const pendingBox = h('div', { class: 'col' });
  const inboxNames = new Set((inbox || []).map((x) => 'grab-inbox/' + x.name));
  const stillWaiting = (inbox || []).filter((x) => x.cmd.cmd === 'add' || x.cmd.cmd === 'add_ig');
  for (const l of LOCAL.slice()) {
    if (l.path && inbox && !inboxNames.has(l.path) && l.stage === 'waiting') { l.stage = 'read'; l.readAt = Date.now(); }
    if (l.stage === 'read' && Date.now() - l.readAt > 5 * 60000) LOCAL.splice(LOCAL.indexOf(l), 1);
    else if (Date.now() - l.at > 30 * 60000) LOCAL.splice(LOCAL.indexOf(l), 1);
  }
  function drawPending() {
    const localPaths = new Set(LOCAL.map((l) => l.path).filter(Boolean));
    const cards = LOCAL.map((l) => {
      const bad = l.stage === 'error', read = l.stage === 'read';
      const text = bad ? l.note : read ? 'The worker read this request. It should be listed below. If it is not, open Activity to see the reason.'
        : l.stage === 'saving' ? 'Saving your request...' : l.stage === 'saved' ? 'Saved. Starting the cloud worker...' : (l.note || 'Saved. Waiting for the cloud worker to pick it up. This usually takes 1 to 3 minutes.');
      return h('div', { class: 'banner ' + (bad ? 'bad' : read ? 'ok' : 'info') }, bad || read ? null : spin(),
        h('div', { class: 'grow' }, h('b', null, `Adding ${l.label}`), h('div', { class: 'small' }, text), read ? h('a', { class: 'small', href: '#/logs' }, 'Open Activity') : null));
    });
    for (const x of stillWaiting) {
      if (localPaths.has('grab-inbox/' + x.name)) continue;
      cards.push(h('div', { class: 'banner info' }, spin(), h('div', { class: 'grow' }, h('b', null, `Waiting to be added: ${describe(x.cmd)}`), h('div', { class: 'small' }, 'Saved. The cloud worker will read it on its next run.'))));
    }
    pendingBox.replaceChildren(...cards);
  }
  drawPending();

  const runBusy = lrun && RUNNING.has(lrun.status);
  const workerBanner = runBusy
    ? h('div', { class: 'banner info' }, spin(), h('div', { class: 'grow' }, h('b', null, lrun.status === 'in_progress' ? 'Cloud worker is working' : 'Cloud worker is starting'),
      h('div', { class: 'small' }, `Started ${ago(lrun.created_at)}. This page refreshes by itself. `, h('a', { href: lrun.html_url, target: '_blank', rel: 'noopener' }, 'Watch the run'))))
    : (lrun && lrun.conclusion === 'failure' && Date.now() - Date.parse(lrun.created_at) < 24 * 3600000
      ? h('div', { class: 'banner warn' }, h('div', { class: 'grow' }, h('b', null, 'The last worker run stopped with an error'),
        h('div', { class: 'small' }, `${ago(lrun.created_at)}. Your videos are safe. `, h('a', { href: lrun.html_url, target: '_blank', rel: 'noopener' }, 'See what happened'), ' or tap Save to Drive again.')))
      : null);

  const livePoll = runBusy || stillWaiting.length || LOCAL.some((l) => ['saving', 'saved', 'waiting'].includes(l.stage));
  if (livePoll) setTimeout(() => { if (location.hash === '#/grab' && !document.hidden) app.rerender(); }, 6000);
  if (jobs.some((j) => ['running', 'queued'].includes(j.status))) setTimeout(() => { if (location.hash === '#/grab' && !document.hidden) app.rerender(); }, 30000);
  return h('div', { class: 'col' }, h('div', { class: 'row' }, h('h1', { class: 'grow', style: 'margin:0' }, 'Save to Drive'), folderLink), permBanner, workerBanner, pendingBox, paused,
    adder,
    jobs.length ? h('div', { class: 'col' }, jobs.map(jobCard)) : h('div', { class: 'card' }, h('p', { class: 'muted', style: 'margin:0' }, 'Nothing saved yet. Paste a link above.')));
}
export { grabView as grab };
