// Long videos: any length (even 24 hours). The worker cuts each video into parts and uploads them to YouTube from the cloud.
import { h, icon, toast, ago, uid, fmtTime } from './core.js';

const hms = (s) => { s = Math.round(s); return `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const PILL = { queued: ['Waiting', ''], running: ['Working', 'warn'], done: ['Finished', 'ok'], failed: ['Needs attention', 'bad'], cancelled: ['Stopped', ''] };
const PART = { pending: 'Waiting', downloading: 'Downloading', uploading: 'Uploading', done: 'Uploaded', failed: 'Failed' };

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
  const res = await S.data.gh(`/repos/${S.repo.owner}/${S.repo.app}/actions/workflows/long.yml/dispatches`, { method: 'POST', body: JSON.stringify({ ref: 'main' }) });
  if (res.status === 404) throw new Error('long.yml was not found in your app repository. Add the file .github/workflows/long.yml first.');
  if (res.status === 403 || res.status === 401) throw new Error('Your GitHub key is not allowed to start runs. It needs the "Actions: read and write" permission.');
  if (!res.ok) throw new Error(`GitHub could not start the run (${res.status}). Is the workflow enabled in the Actions tab?`);
}

async function send(S, cmd) {
  await S.data.put(`long-inbox/${Date.now()}-${uid()}.json`, cmd, 'Reelio long videos: ' + cmd.cmd);
}

export async function longView(S, params, app) {
  let data;
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
  const go = h('button', { class: 'btn primary', onclick: async (e) => {
    const links = f.links.split(/\s+/).map((x) => x.trim()).filter(Boolean);
    if (f.mode === 'links' && !links.length) return toast('Paste at least one video link.', 5000);
    if (f.mode === 'channel' && !f.handle.trim()) return toast('Type the channel name, like @yourchannel.', 5000);
    if (!googles.length) return toast('Connect Google first in Accounts.', 5000);
    e.currentTarget.disabled = true;
    try {
      await send(S, { cmd: 'add', links: f.mode === 'links' ? links : [], channel: f.mode === 'channel' ? { handle: f.handle.trim(), tab: f.tab, min_minutes: f.min_minutes, max_videos: f.max_videos } : null,
        settings: { conn: f.conn, part_hours: f.part_hours, quality: f.quality, privacy: f.privacy, title_template: f.title_template, description: f.description } });
      await startWorker(S);
      toast('Started. The video appears below in about a minute.', 5000);
      setTimeout(() => app.rerender(), 4000);
    } catch (err) { toast(err.message, 7000); e.currentTarget.disabled = false; }
  } }, icon('play'), 'Start');

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

  if (jobs.some((j) => ['running', 'queued'].includes(j.status))) setTimeout(() => { if (location.hash === '#/long' && !document.hidden) app.rerender(); }, 30000);
  return h('div', { class: 'col' }, h('h1', null, 'Long videos'), paused,
    jobs.length ? h('div', { class: 'col' }, jobs.map(jobCard)) : h('div', { class: 'card' }, h('p', { class: 'muted', style: 'margin:0' }, 'Nothing here yet. Add a video below.')),
    adder);
}
export { longView as long };
