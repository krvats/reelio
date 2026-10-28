// Demo mode (app.html?demo=1): the real app running on invented sample data, entirely in this browser tab.
// Nothing is sent anywhere and nothing is saved. Reloading starts the demo fresh.
const MIN = 60e3, HOUR = 3600e3;
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
const hhmm = (ms) => { const d = new Date(ms); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };

const PALETTES = [['#ff9a62', '#7b2ff7'], ['#43e97b', '#0b6a84'], ['#f9d423', '#e5352b'], ['#6dd5ed', '#2b32b2'], ['#f857a6', '#ff5858'], ['#a8e063', '#056ba1'], ['#fbc2eb', '#6a82fb'], ['#ffd89b', '#19547b']];
function thumb(i) {
  const [a, b] = PALETTES[i % PALETTES.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 92"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="64" height="92" fill="url(#g)"/><circle cx="${18 + (i * 7) % 28}" cy="26" r="9" fill="#fff" fill-opacity=".85"/><path d="M0 92V70l18-14 16 12 14-10 16 12v22z" fill="#000" fill-opacity=".28"/><path d="M26 40l14 8-14 8z" fill="#fff" fill-opacity=".0"/></svg>`;
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}

const ACCOUNTS = [
  { id: 'ig_wander', kind: 'instagram', label: 'wanderframe', ig_user_id: '1001' },
  { id: 'ig_chai', kind: 'instagram', label: 'chaiandcode', ig_user_id: '1002' },
  { id: 'ig_paws', kind: 'instagram', label: 'pixelpaws', ig_user_id: '1003' },
  { id: 'ig_fit', kind: 'instagram', label: 'fitfuel.daily', ig_user_id: '1004' },
  { id: 'yt_wander', kind: 'google', label: 'Wanderframe Shorts' },
  { id: 'yt_paws', kind: 'google', label: 'Pixel Paws' },
  { id: 'google', kind: 'google', label: 'Google (Drive + YouTube)' },
  { id: 'cloudinary', kind: 'cloudinary', label: 'Cloudinary' },
  { id: 'telegram', kind: 'telegram', label: 'Telegram' },
];
const sched = (n, extra = {}) => ({ per_day: n, start: '00:00', end: '23:59', jitter: 0.2, max_per_run: 3, gap_seconds: 90, scan_every_min: 30, ...extra });
const ROUTES = [
  { id: 'wander_ig', name: 'Travel reels to wanderframe', source: { type: 'drive', conn: 'google', folders: ['Travel reels'] }, target: { type: 'instagram', conn: 'ig_wander' }, n: 6, caption: { mode: 'same', text: 'Somewhere you should be right now {emoji} {hashtags}' }, edit: { filter: 'golden', fit: 'keep', strength: 0.6 }, names: ['Lisbon tram at dawn', 'Rooftop chai in Jaipur', 'Hampi sunset drone', 'Night market Bangkok', 'Kyoto rain walk', 'Snow train Manali', 'Santorini steps', 'Desert camp Jaisalmer', 'Ha Long Bay boat', 'Old Delhi lanes', 'Goa monsoon road', 'Cappadocia balloons'] },
  { id: 'wander_yt', name: 'Travel shorts to Wanderframe Shorts', source: { type: 'drive', conn: 'google', folders: ['Travel shorts'] }, target: { type: 'youtube', conn: 'yt_wander' }, n: 3, caption: { mode: 'same', text: '{name} #shorts #travel' }, edit: { filter: 'clean_pop', fit: 'blur' }, names: ['Tram 28 in 20 seconds', 'Street food in Hanoi', 'Alpine train views', 'Hidden beach in Krabi', 'Tokyo crossing timelapse', 'Sunrise at Tiger Hill'] },
  { id: 'chai_ig', name: 'Chai & Code YouTube to Instagram', source: { type: 'youtube', conn: 'google', net_conn: 'youtube-net', handle: '@chaiandcode', url: 'https://www.youtube.com/@chaiandcode/shorts' }, target: { type: 'instagram', conn: 'ig_chai' }, n: 4, caption: { mode: 'same', text: '{name} {hashtags}' }, edit: { filter: 'none', fit: 'crop' }, names: ['When the build passes on Friday', 'Git blame hits different', 'Tabs vs spaces, settled', 'Debugging with chai', 'The 3AM deploy', 'Stack Overflow, 2012 vs now', 'Rubber duck therapy', 'One more console.log'] },
  { id: 'paws_ig', name: 'Pet clips to pixelpaws', source: { type: 'upload', conn: '' }, target: { type: 'instagram', conn: 'ig_paws' }, n: 8, caption: { mode: 'random', text: 'Good boy of the day {emoji}' }, edit: { filter: 'warm', fit: 'keep' }, names: ['Corgi vs vacuum', 'Kitten finds the mirror', 'Zoomies at the park', 'Parrot says hello', 'Puppy first snow', 'Cat chef assistant', 'Golden retriever hug', 'Hamster marathon', 'Sleepy pug', 'Bunny binky', 'Husky opinions', 'Otter holding hands'] },
  { id: 'paws_yt', name: 'Pet shorts to Pixel Paws', source: { type: 'drive', conn: 'google', folders: ['Pet shorts'] }, target: { type: 'youtube', conn: 'yt_paws' }, n: 3, caption: { mode: 'same', text: '{name} #shorts #pets' }, edit: { filter: 'warm', fit: 'blur' }, names: ['Corgi vs vacuum', 'Kitten finds the mirror', 'Parrot says hello', 'Puppy first snow'] },
  { id: 'fit_ig', name: 'Gym motivation to fitfuel.daily', source: { type: 'drive', conn: 'google', folders: ['Gym'] }, target: { type: 'instagram', conn: 'ig_fit' }, n: 10, enabled: false, caption: { mode: 'same', text: 'Show up. {hashtags}' }, edit: { filter: 'vivid', fit: 'crop' }, names: ['Deadlift PR', 'Morning mobility', '5 minute core', 'Sunday long run'] },
];

export function makeDemo() {
  const now = Date.now(); seed = 7;
  const files = new Map();
  const status = { accounts: {}, routes: {}, notified: {}, license: { enforced: false, active: true, plan: 'open', message: '' }, paused: false, version: 1, plan: {}, plan_week: {}, todo: [], recent: [], cookies: { total: 3, ready: 3, resting: 0, parked: 0, next_at: null, items: [] } };
  const routes = [], logs = [], ledger = [];
  let postedAll = 0;

  for (const a of ACCOUNTS) {
    status.accounts[a.id] = { label: a.label, kind: a.kind, connected: true, ok: true, rate_hits: 0, last_post_at: iso(now - (20 + rnd() * 90) * MIN), ...(a.kind === 'instagram' ? { token_expires: iso(now + (24 + Math.floor(rnd() * 30)) * 24 * HOUR) } : {}) };
  }
  status.accounts['youtube-net'] = { label: 'YouTube downloads', kind: 'ytnet', connected: true, ok: true };
  ACCOUNTS.push({ id: 'youtube-net', kind: 'ytnet', label: 'YouTube downloads' });

  ROUTES.forEach((def, ri) => {
    const r = { id: def.id, name: def.name, enabled: def.enabled !== false, source: def.source, target: def.target, share_to_feed: true, schedule: sched(def.n), caption: { hashtag_sets: [], variants: [], ...def.caption }, edit: { audio: 'keep', ...def.edit }, order: 'oldest' };
    // today's plan: about half the slots are already behind us, whatever time the demo is opened
    const k = Math.round(def.n * 0.5), gap = Math.max(40, Math.min(150, Math.floor(1080 / def.n))) * MIN;
    const slots = []; for (let i = 0; i < def.n; i++) { const t = now + (i - k + 0.4) * gap + (rnd() - 0.5) * gap * 0.3; slots.push({ at: iso(t), state: t < now ? 'done' : 'later', ms: t }); }
    const first = slots[0].ms - 20 * MIN, last = slots[slots.length - 1].ms + 20 * MIN;
    if (new Date(first).getDate() === new Date(last).getDate()) { r.schedule.start = hhmm(first); r.schedule.end = hhmm(last); }
    routes.push(r);
    // queue
    const items = []; const names = def.names;
    names.forEach((nm, i) => {
      const posted = i < k + 2 && r.enabled;
      const it = { key: 'drive:' + def.id + i, status: posted ? 'posted' : 'pending', fails: 0, added_at: iso(now - 3 * 24 * HOUR), name: nm + '.mp4', md5: 'demo' + ri + i, size: 8e6 + i * 9e5, created: iso(now - (20 - i) * 24 * HOUR), thumb: thumb(ri * 3 + i), meta: {}, last_error: null, post_now: false, allow_repost: false };
      if (posted) { it.posted_at = iso(now - (k + 2 - i) * 1.4 * HOUR); it.media_id = 'M' + ri + i; it.permalink = '#'; it.status = 'posted'; ledger.push({ id: 'l' + ri + i, route: def.id, target: def.target.type + ':' + def.target.conn, src: it.key, md5: it.md5, name: it.name, media_id: it.media_id, permalink: '#', title: nm, at: it.posted_at, status: 'posted' }); }
      items.push(it);
    });
    if (def.id === 'chai_ig') { const f = items.find((x) => x.status === 'pending'); if (f) { f.status = 'failed'; f.fails = 3; f.last_error = { msg: 'Instagram does not accept this video\'s format.', fix: 'Reelio re-encodes videos; tap Try again, or pick another fit mode in Look.' }; } }
    files.set('queues/' + def.id + '.json', { items, last_scan: iso(now - 12 * MIN) });
    const doneN = slots.filter((s) => s.state === 'done').length;
    const rs = { name: def.name, today_posted: r.enabled ? doneN : 0, today_target: r.enabled ? def.n : 0, next_slot: r.enabled ? (slots.find((s) => s.state !== 'done') || {}).at : null, pending: items.filter((x) => x.status === 'pending').length, failed: items.filter((x) => x.status === 'failed').length, posted_total: items.filter((x) => x.status === 'posted').length + 40 + ri * 17, state: r.enabled ? 'ok' : 'disabled', message: '' };
    if (r.enabled) { status.plan[def.id] = slots.map(({ at, state }) => ({ at, state })); status.plan_week[def.id] = Array.from({ length: 7 }, (_, d) => ({ date: new Date(now + d * 24 * HOUR).toLocaleDateString('en-CA'), n: def.n })); postedAll += doneN; }
    if (def.id === 'paws_yt') { rs.problem = { msg: 'YouTube\'s daily upload limit for this channel is reached.', fix: 'Nothing to do. Posting resumes tomorrow. New channels can upload only a few videos a day; verifying the channel with a phone number raises it.', kind: 'quota' }; status.accounts.yt_paws.ok = false; status.accounts.yt_paws.problem = rs.problem; status.accounts.yt_paws.cooldown_until = iso(now + 6 * HOUR); }
    status.routes[def.id] = rs;
    slots.filter((s) => s.state === 'done' && r.enabled).slice(-2).forEach((s, i) => { const ev = { at: s.at, level: 'ok', route: def.id, msg: `Posted '${names[(i + 1) % names.length]}.mp4'` }; status.recent.push(ev); logs.push(ev); });
  });
  status.recent.sort((a, b) => (a.at < b.at ? 1 : -1)); status.recent = status.recent.slice(0, 40);
  status.recent.unshift({ at: iso(now - 25 * MIN), level: 'warn', route: 'chai_ig', msg: 'Gym clip failed once: Instagram does not accept this video\'s format.', fix: 'Reelio re-encodes videos and tries again.' });
  logs.push(...status.recent);
  status.run = { started: iso(now - 4 * MIN), finished: iso(now - 4 * MIN + 9000), seconds: 9, result: 'ok', posted: 2, message: '' };
  status.updated = iso(now);
  status.todo = [{ kind: 'done', text: `${postedAll} videos posted today across 5 pages.` }, { kind: 'pending', text: 'Next post in a few minutes.' }, { kind: 'action', text: 'Pixel Paws hit YouTube\'s daily limit. It resumes by itself tomorrow.' }];

  const cfg = { version: 1, paused: false, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata', notify: { telegram: { enabled: true, conn: 'telegram', events: { posted: false, failed: true, limit: true, token: true, daily: true } } }, connections: ACCOUNTS.filter((a) => a.id !== 'youtube-net').concat([{ id: 'youtube-net', kind: 'ytnet', label: 'YouTube downloads' }]), routes, cookie_count: 3 };
  files.set('config.json', cfg); files.set('status.json', status); files.set('ledger.json', { entries: ledger, inflight: {} });
  files.set('diagnose.json', { at: iso(now - 30 * MIN), ok: true, verdict: 'Everything is connected and working.', checks: ACCOUNTS.map((a) => ({ id: a.id, title: `${a.label} (${a.kind})`, ok: a.id !== 'yt_paws', detail: a.kind === 'instagram' ? `@${a.label} · MEDIA_CREATOR · 100 posts` : a.id === 'yt_paws' ? 'daily upload limit reached' : 'login works', fix: a.id === 'yt_paws' ? 'Nothing to do. Posting resumes tomorrow.' : '' })) });
  // analytics: believable reels with different numbers
  const an = { at: iso(now), accounts: {}, daily: {} };
  ACCOUNTS.filter((a) => a.kind === 'instagram').forEach((a, ai) => {
    const posts = Array.from({ length: 8 }, (_, i) => ({ id: 'P' + ai + i, at: iso(now - (i * 5 + 2) * HOUR), permalink: '#', caption: ROUTES[[0, 2, 3, 5][ai]].names[i % 4], likes: Math.round(120 + rnd() * 900 * (ai + 1) / 2), comments: Math.round(4 + rnd() * 60), reach: Math.round(1800 + rnd() * 9000), views: Math.round(2600 + rnd() * 14000), shares: Math.round(5 + rnd() * 90), saved: Math.round(8 + rnd() * 140) }));
    const tot = posts.reduce((t, p) => { for (const k of ['likes', 'comments', 'reach', 'views', 'shares', 'saved']) t[k] = (t[k] || 0) + p[k]; return t; }, {});
    an.accounts[a.id] = { label: a.label, posts, best_hours: [12 + ai, 19, 21], totals: tot };
  });
  ROUTES.forEach((d) => { an.daily[d.id] = Object.fromEntries(Array.from({ length: 14 }, (_, i) => [new Date(now - (13 - i) * 24 * HOUR).toLocaleDateString('en-CA'), Math.round(d.n * (0.7 + rnd() * 0.3))])); });
  files.set('analytics.json', an);
  files.set('logs/' + new Date(now).toISOString().slice(0, 7) + '.jsonl', logs.sort((a, b) => (a.at < b.at ? -1 : 1)).map((l) => JSON.stringify(l)).join('\n'));
  return new DemoData(files);
}

class DemoData {
  constructor(files) { this.f = files; this.r = { owner: 'demo', app: 'reelio', data: 'reelio-data', api: '' }; this.token = 'demo'; }
  async read(p) { const v = this.f.get(p); if (v === undefined || typeof v === 'string') return null; return structuredClone(v); }
  async readText(p) { const v = this.f.get(p); return v == null ? null : (typeof v === 'string' ? v : JSON.stringify(v)); }
  async sha(p) { return this.f.has(p) ? 'demo' : null; }
  async put(p, c) { this.f.set(p, structuredClone(c)); return {}; }
  async update(p, fn, msg, fallback = {}) { const cur = this.f.has(p) ? structuredClone(this.f.get(p)) : structuredClone(fallback); const next = await fn(cur); this.f.set(p, structuredClone(next)); return next; }
  async remove(p) { this.f.delete(p); }
  async list(dir) { return [...this.f.keys()].filter((k) => k.startsWith(dir + '/')).map((k) => ({ name: k.slice(dir.length + 1), path: k })); }
  async listSecretNames() { return ['DATA_PAT', 'REELIO_KEY']; }
  async latestRun() { return { status: 'completed', conclusion: 'success' }; }
  async check() { return { token: true, login: 'demo', dataRepo: true, appRepo: true, hasConfig: true }; }
  async command(c) {
    const q = this.f.get('queues/' + c.route + '.json'); if (!q) return;
    const it = (k) => q.items.find((x) => x.key === k);
    if (c.cmd === 'skip' && it(c.key)) it(c.key).status = 'skipped';
    if ((c.cmd === 'unskip' || c.cmd === 'retry' || c.cmd === 'repost') && it(c.key)) { it(c.key).status = 'pending'; it(c.key).fails = 0; it(c.key).last_error = null; }
    if (c.cmd === 'post_now' && it(c.key)) it(c.key).post_now = true;
    if (c.cmd === 'caption' && it(c.key)) it(c.key).caption_override = c.caption || '';
    if (c.cmd === 'reorder') c.keys.forEach((k, n) => { if (it(k)) it(k).order = n; });
  }
  // "Check now": pretend the cloud worker ran once and posted the next video of each running flow
  async dispatch(action) {
    const st = this.f.get('status.json'), cfg = this.f.get('config.json'); const now = Date.now();
    if (action === 'run' || !action) {
      let n = 0;
      for (const r of cfg.routes) {
        if (r.enabled === false) continue; const rs = st.routes[r.id]; if (!rs || rs.problem) continue;
        const q = this.f.get('queues/' + r.id + '.json'); const it = q && q.items.find((x) => x.status === 'pending'); if (!it) continue;
        it.status = 'posted'; it.posted_at = iso(now); it.permalink = '#'; rs.today_posted = (rs.today_posted || 0) + 1; rs.pending = Math.max(0, (rs.pending || 1) - 1); rs.posted_total = (rs.posted_total || 0) + 1;
        const slot = (st.plan[r.id] || []).find((s) => s.state !== 'done'); if (slot) slot.state = 'done';
        st.recent.unshift({ at: iso(now), level: 'ok', route: r.id, msg: `Posted '${it.name}'` }); n++;
      }
      st.run = { started: iso(now), finished: iso(now), seconds: 8, result: 'ok', posted: n, message: '' };
    }
    st.updated = iso(now);
  }
}
