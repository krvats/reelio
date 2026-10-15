// Long videos: any length (even 24 hours). The worker cuts each video into parts and uploads them to YouTube from the cloud.
import { h, icon, toast, ago, uid, fmtTime } from './core.js';

const hms = (s) => { s = Math.round(s); return `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const PILL = { queued: ['Waiting', ''], running: ['Working', 'warn'], done: ['Finished', 'ok'], failed: ['Needs attention', 'bad'], cancelled: ['Stopped', ''] };
const PART = { pending: 'Waiting', downloading: 'Downloading', uploading: 'Uploading', done: 'Uploaded', failed: 'Failed' };

// ---- added: instant feedback while a request travels to the cloud worker ----
const LOCAL = [];          // requests added from this screen: { id, label, at, stage: 'saving' | 'saved' | 'waiting' | 'read' | 'error', path, note }
const RUNNING = new Set(['queued', 'in_progress', 'waiting', 'pending', 'requested']);
let defaultRef = null;

async function loadInbox(S) {
  if (typeof S.data.list !== 'function') return null;                 // hosted mode: no inbox folder
  const files = (await S.data.list('long-inbox')).filter((f) => f.name && f.name.endsWith('.json'));
  const items = await Promise.all(files.slice(0, 8).map(async (f) => { const c = await S.data.read('long-inbox/' + f.name).catch(() => null); return { name: f.name, cmd: c || {} }; }));
  return items;
}

async function latestLongRun(S) {
  const res = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}/actions/workflows/long.yml/runs?per_page=1`, { cache: 'no-store' });
  if (!res.ok) return null;
  return ((await res.json()).workflow_runs || [])[0] || null;
}

const describe = (c) => (c.channel && c.channel.handle ? `channel ${c.channel.handle}` : `${(c.links || []).length || 1} video link${(c.links || []).length === 1 ? '' : 's'}`);
const spin = () => h('span', { class: 'spinner', 'aria-hidden': 'true' });

async function loadJobs(S) {
  const res = await S.data.gh(S.data.base() + 'queues/long', { cache: 'no-store' });
  if (res.status === 404) return { jobs: [], state: {} };
  if (!res.ok) throw new Error(`Could not read the long video list (${res.status}).`);
  const files = (await res.json()).filter((f) => f.name.endsWith('.json'));
  const state = (await S.data.read('queues/long/_state.json')) || {};
  const jobs = (await Promise.all(files.filter((f) => !f.name.startsWith('_')).slice(0, 40).map((f) => S.data.read('queues/long/' + f.name)))).filter((j) => j && j.parts);
  jobs.sort((a, b) => (b.created || '').localeCompare(a.created || ''));
  return { jobs, state };
}

async function startWorker(S) {
  if (!defaultRef) { try { const r = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}`); defaultRef = r.ok ? (await r.json()).default_branch || 'main' : 'main'; } catch { defaultRef = 'main'; } }
  const res = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}/actions/workflows/long.yml/dispatches`, { method: 'POST', body: JSON.stringify({ ref: defaultRef }) });
  if (res.status === 404) throw new Error('long.yml was not found in your app repository. Add the file .github/workflows/long.yml first.');
  if (res.status === 403 || res.status === 401) throw new Error('Your GitHub key is not allowed to start runs. It needs the "Actions: read and write" permission.');
  if (!res.ok) throw new Error(`GitHub could not start the run (${res.status}). Is the workflow enabled in the Actions tab?`);
}

async function send(S, cmd) {
  const path = `long-inbox/${Date.now()}-${uid()}.json`;
  await S.data.put(path, cmd, 'Reelio long videos: ' + cmd.cmd);
  return path;
}

export async function longView(S, params, app) {
  let data;
  const [inbox, lrun] = await Promise.all([loadInbox(S).catch(() => null), latestLongRun(S).catch(() => null)]);
  try { data = await loadJobs(S); } catch (e) { return h('div', { class: 'card' }, h('h1', null, 'Long videos'), h('p', null, e.message), h('button', { class: 'btn', onclick: () => app.rerender() }, 'Try again')); }
  const { jobs, state } = data;
  const googles = (S.cfg.connections || []).filter((c) => c.kind === 'google');
  const f = { mode: 'links', links: '', handle: '', tab: 'both', min_minutes: 20, max_videos: 3, conn: (googles[0] || {}).id || 'google', part_hours: 4, quality: '720', privacy: 'private',
    title_template: '{title} (Part {n}/{total})', description: '{title}\n\nPart {n} of {total}' };

  const field = (label, input, hint) => h('label', { class: 'col', style: 'gap:4px' }, h('b', null, label), input, hint ? h('span', { class: 'small muted' }, hint) : null);
  const sel = (key, opts, num) => h('select', { onchange: (e) => { f[key] = num ? +e.target.value : e.target.value; if (key === 'mode') draw(); } }, opts.map(([v, l]) => h('option', { value: v, selected: String(f[key]) === String(v) }, l)));
  const inp = (key, type = 'text', extra = {}) => h('input', { type, value: f[key], ...extra, oninput: (e) => { f[key] = type === 'number' ? +e.target.value : e.target.value; } });
  const modeBox = h('div', { class: 'col' });
  function draw() {
    modeBox.replaceChildren(...(f.mode === 'links'
      ? [field('Video links', h('textarea', { rows: 3, placeholder: 'https://www.youtube.com/watch?v=...', 'aria-label': 'Video links', oninput: (e) => { f.links = e.target.value; } }, f.links), 'One link per line. Finished live streams work too.')]
      : [field('Channel', inp('handle', 'text', { placeholder: '@yourchannel' }), 'Only a channel you own or have permission to reuse.'),
        field('Look in', sel('tab', [['both', 'Videos and past live streams'], ['streams', 'Past live streams only'], ['videos', 'Videos only']])),
        field('Only videos at least this long (minutes)', inp('min_minutes', 'number', { min: 1 })),
        field('How many of the newest to add', inp('max_videos', 'number', { min: 1, max: 50 }))]));
  }
  draw();
  const goLabel = [icon('play'), 'Start'];
  const go = h('button', { class: 'btn primary', onclick: async (e) => {
    const btn = e.currentTarget;                      // keep it: e.currentTarget is empty after the first await
    const links = f.links.split(/\s+/).map((x) => x.trim()).filter(Boolean);
    if (f.mode === 'links' && !links.length) return toast('Paste at least one video link.', 5000);
    if (f.mode === 'channel' && !f.handle.trim()) return toast('Type the channel name, like @yourchannel.', 5000);
    if (!googles.length) return toast('Connect Google first in Accounts.', 5000);
    const cmd = { cmd: 'add', links: f.mode === 'links' ? links : [], channel: f.mode === 'channel' ? { handle: f.handle.trim(), tab: f.tab, min_minutes: f.min_minutes, max_videos: f.max_videos } : null,
      settings: { conn: f.conn, part_hours: f.part_hours, quality: f.quality, privacy: f.privacy, title_template: f.title_template, description: f.description } };
    btn.disabled = true; btn.replaceChildren(spin(), ' Adding...');
    const me = { id: uid(), label: describe(cmd), at: Date.now(), stage: 'saving' };
    LOCAL.unshift(me); drawPending();                 // the card shows up at once, before anything travels over the internet
    pendingBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
    try {
      me.path = await send(S, cmd); me.stage = 'saved'; drawPending();
      try { await startWorker(S); me.stage = 'waiting'; me.note = ''; toast('Added. The cloud worker is starting.', 4000); }
      catch (err) { me.stage = 'waiting'; me.note = `Saved, but the worker could not be started right now: ${err.message} It will still pick this up by itself within the hour.`; toast('Saved. ' + err.message, 8000); }
      drawPending();
      f.links = ''; draw();
      setTimeout(() => app.rerender(), 5000);
    } catch (err) {
      me.stage = 'error'; me.note = err.message; drawPending();
      toast(err.message, 7000);
    } finally { btn.disabled = false; btn.replaceChildren(...goLabel); }
  } }, goLabel);

  const adder = h('div', { class: 'card col' }, h('h2', { style: 'margin:0' }, 'Add long videos'),
    h('p', { class: 'muted', style: 'margin:0' }, 'Any length, even 24 hours. Reelio cuts each video into parts and uploads every part to your YouTube channel from the cloud. Nothing needs your computer. Only use videos you own or have permission to reuse.'),
    field('Add by', sel('mode', [['links', 'Video links'], ['channel', 'Look through a channel']])), modeBox,
    field('Upload to', h('select', { onchange: (e) => { f.conn = e.target.value; } }, (googles.length ? googles : [{ id: 'google', label: 'Google' }]).map((c) => h('option', { value: c.id, selected: c.id === f.conn }, c.label)))),
    h('div', { class: 'grid' },
      field('Longest part', sel('part_hours', [[1, '1 hour'], [2, '2 hours'], [3, '3 hours'], [4, '4 hours'], [6, '6 hours'], [8, '8 hours']], true), 'Longer parts need more disk on the cloud runner.'),
      field('Quality', sel('quality', [['480', '480p (smallest)'], ['720', '720p (recommended)'], ['1080', '1080p (large)']])),
      field('Visibility', sel('privacy', [['private', 'Private (check first)'], ['unlisted', 'Unlisted'], ['public', 'Public']]))),
    field('Title of each part', inp('title_template'), 'You can use {title}, {n} (part number) and {total}.'),
    field('Description', h('textarea', { rows: 3, oninput: (e) => { f.description = e.target.value; } }, f.description), 'Also accepts {url} for the original video link.'),
    h('div', { class: 'row' }, go),
    h('p', { class: 'small muted', style: 'margin:0' }, 'YouTube only accepts videos over 15 minutes from a phone-verified channel (youtube.com/verify). Each upload uses part of YouTube\'s daily allowance, about 6 uploads a day for a new Google project, so a 24 hour video in 4 hour parts takes about a day.'));

  const until = (s) => (s && new Date(s) > new Date() ? new Date(s) : null);
  const waits = [until(state.source_until), ...Object.values(state.conn_until || {}).map(until)].filter(Boolean);
  const paused = waits.length ? h('div', { class: 'banner warn' }, h('div', null, h('b', null, 'Paused for now. '),
    `Long videos wait until about ${fmtTime(new Date(Math.max(...waits)).toISOString(), S.tz)} (YouTube blocked the download or the daily upload limit was reached). It continues by itself.`)) : null;

  const jobCard = (j) => {
    const done = j.parts.filter((p) => p.status === 'done').length, [label, cls] = PILL[j.status] || ['', ''];
    const failed = j.parts.some((p) => p.status === 'failed');
    const act = async (cmd, msg) => { try { await send(S, { cmd, id: j.id }); await startWorker(S).catch(() => {}); toast(msg, 4000); setTimeout(() => app.rerender(), 3500); } catch (e) { toast(e.message, 6000); } };
    return h('div', { class: 'card col' },
      h('div', { class: 'row' }, h('h2', { class: 'grow', style: 'margin:0;word-break:break-word' }, j.title), h('span', { class: 'pill ' + cls }, label)),
      h('p', { class: 'muted', style: 'margin:0' }, `${hms(j.duration)} long. ${done} of ${j.parts.length} parts uploaded.`),
      h('div', { style: 'height:8px;border-radius:99px;background:var(--line);overflow:hidden', role: 'progressbar', 'aria-valuenow': done, 'aria-valuemax': j.parts.length },
        h('div', { style: `height:100%;width:${Math.round(done / j.parts.length * 100)}%;background:var(--brand)` })),
      h('div', { class: 'col', style: 'gap:6px' }, j.parts.map((p) => h('div', { class: 'row gap-s', style: 'align-items:flex-start' },
        h('span', { class: 'pill ' + (p.status === 'done' ? 'ok' : p.status === 'failed' ? 'bad' : p.status === 'pending' ? '' : 'warn'), style: 'min-width:92px;justify-content:center' }, PART[p.status] || p.status),
        h('div', { class: 'grow small' }, `Part ${p.n}: ${hms(p.start)} to ${hms(p.end)} `, p.url ? h('a', { href: p.url, target: '_blank', rel: 'noopener' }, 'Open on YouTube') : null,
          p.last_error && p.status !== 'done' ? h('div', { class: 'muted' }, p.last_error.msg + ' ' + (p.last_error.fix || '')) : null)))),
      h('div', { class: 'row gap-s' },
        failed ? h('button', { class: 'btn small', onclick: () => act('retry', 'Trying the failed parts again.') }, icon('refresh'), 'Try failed parts again') : null,
        !['done', 'cancelled'].includes(j.status) ? h('button', { class: 'btn small', onclick: () => act('cancel', 'Stopped. Parts already uploaded stay on YouTube.') }, 'Stop') : null,
        ['done', 'cancelled', 'failed'].includes(j.status) ? h('button', { class: 'btn small danger', onclick: () => act('remove', 'Removed from this list.') }, 'Remove from list') : null),
      h('p', { class: 'small muted', style: 'margin:0' }, `Updated ${ago(j.updated)}.`));
  };

  // ---- added: what is happening right now (requests on their way + the cloud worker itself) ----
  const pendingBox = h('div', { class: 'col' });
  const inboxNames = new Set((inbox || []).map((x) => 'long-inbox/' + x.name));
  const stillWaiting = (inbox || []).filter((x) => x.cmd.cmd === 'add');
  for (const l of LOCAL.slice()) {                    // a request that left the inbox was read by the worker
    if (l.path && inbox && !inboxNames.has(l.path) && l.stage === 'waiting') { l.stage = 'read'; l.readAt = Date.now(); }
    if (l.stage === 'read' && Date.now() - l.readAt > 5 * 60000) LOCAL.splice(LOCAL.indexOf(l), 1);
    else if (Date.now() - l.at > 30 * 60000) LOCAL.splice(LOCAL.indexOf(l), 1);
  }
  function drawPending() {
    const localPaths = new Set(LOCAL.map((l) => l.path).filter(Boolean));
    const cards = LOCAL.map((l) => {
      const bad = l.stage === 'error', read = l.stage === 'read';
      const text = bad ? l.note : read ? 'The worker read this request. The video should be listed below. If it is not, open Activity to see the reason.'
        : l.stage === 'saving' ? 'Saving your request...' : l.stage === 'saved' ? 'Saved. Starting the cloud worker...' : (l.note || 'Saved. Waiting for the cloud worker to pick it up. This usually takes 1 to 3 minutes.');
      return h('div', { class: 'banner ' + (bad ? 'bad' : read ? 'ok' : 'info') }, bad || read ? null : spin(),
        h('div', { class: 'grow' }, h('b', null, `Adding ${l.label}`), h('div', { class: 'small' }, text), read ? h('a', { class: 'small', href: '#/logs' }, 'Open Activity') : null));
    });
    for (const x of stillWaiting) {                   // requests made earlier or on another device
      if (localPaths.has('long-inbox/' + x.name)) continue;
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
        h('div', { class: 'small' }, `${ago(lrun.created_at)}. Your videos are safe. `, h('a', { href: lrun.html_url, target: '_blank', rel: 'noopener' }, 'See what happened'), ' or tap Start again.')))
      : null);

  const livePoll = runBusy || stillWaiting.length || LOCAL.some((l) => ['saving', 'saved', 'waiting'].includes(l.stage));
  if (livePoll) setTimeout(() => { if (location.hash === '#/long' && !document.hidden) app.rerender(); }, 6000);
  if (jobs.some((j) => ['running', 'queued'].includes(j.status))) setTimeout(() => { if (location.hash === '#/long' && !document.hidden) app.rerender(); }, 30000);
  return h('div', { class: 'col' }, h('h1', null, 'Long videos'), workerBanner, pendingBox, paused,
    jobs.length ? h('div', { class: 'col' }, jobs.map(jobCard)) : h('div', { class: 'card' }, h('p', { class: 'muted', style: 'margin:0' }, 'Nothing here yet. Add a video below.')),
    adder);
}
export { longView as long };
