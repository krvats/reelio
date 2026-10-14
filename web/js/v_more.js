import { h, icon, toast, fmtTime, fmtDay, ago, LS } from './core.js';
import { saveCfg, runNow, S as GS } from './app.js';

export async function more() {
  const L = [['schedule', 'Schedule', 'When each post is planned today'], ['analytics', 'Stats', 'Views, likes and best times'], ['logs', 'Activity', 'What Reelio did, in plain words'], ['settings', 'Settings', 'Time zone, text size, alerts, backup'], ['help', 'Help', 'Why is it failing? Quick answers']];
  return h('div', { class: 'col' }, h('h1', null, 'More'), L.map(([k, t, d]) => h('a', { class: 'card', href: '#/' + k, style: 'text-decoration:none;color:inherit' }, h('h2', { style: 'margin:0' }, t), h('span', { class: 'muted' }, d))));
}

export async function schedule(S) {
  const plan = S.status.plan || {}, routes = (S.cfg.routes || []).filter((r) => r.enabled !== false);
  if (!routes.length) return h('div', { class: 'card' }, h('h1', null, 'Schedule'), h('p', null, 'No flows yet.'), h('a', { class: 'btn primary', href: '#/flows/new' }, 'Create a flow'));
  return h('div', { class: 'col' }, h('h1', null, 'Schedule'), h('p', { class: 'muted' }, `Today's plan in ${S.tz}. Times shift by a few minutes each day so posting looks natural.`),
    routes.map((r) => {
      const slots = plan[r.id] || [];
      return h('div', { class: 'card col' }, h('h2', { style: 'margin:0' }, r.name), h('p', { class: 'muted', style: 'margin:0' }, `${r.schedule.per_day} a day between ${r.schedule.start} and ${r.schedule.end}`),
        slots.length ? h('div', { class: 'row gap-s' }, slots.map((s) => h('span', { class: 'pill ' + (s.state === 'done' ? 'ok' : s.state === 'due' ? 'warn' : '') }, fmtTime(s.at, S.tz) + (s.state === 'done' ? ' done' : '')))) : h('p', { class: 'muted' }, 'The plan appears after the next check.'),
        h('a', { class: 'small', href: '#/flows/' + r.id }, 'Change this schedule'));
    }));
}

export async function analytics(S) {
  const a = (await S.data.read('analytics.json')) || {};
  const days = []; for (let i = 29; i >= 0; i--) { const d = new Date(Date.now() - i * 864e5).toLocaleDateString('en-CA', { timeZone: S.tz }); days.push(d); }
  const per = days.map((d) => Object.values(a.daily || {}).reduce((s, m) => s + (m[d] || 0), 0)), max = Math.max(1, ...per);
  const accts = Object.values(a.accounts || {});
  const posts = accts.flatMap((x) => x.posts || []).sort((p, q) => (q.reach || 0) - (p.reach || 0)).slice(0, 8);
  const tot = accts.reduce((s, x) => { for (const k of ['views', 'reach', 'likes', 'comments']) s[k] = (s[k] || 0) + ((x.totals || {})[k] || 0); return s; }, {});
  const best = accts.flatMap((x) => x.best_hours || []).slice(0, 3);
  const csv = async () => {
    const led = (await S.data.read('ledger.json')) || { entries: [] };
    const rows = [['posted_at', 'flow', 'account', 'name', 'link']].concat(led.entries.map((e) => [e.at, e.route, e.target, e.name, e.permalink]));
    const text = rows.map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); const el = h('a', { href: url, download: 'reelio-posts.csv' }); document.body.append(el); el.click(); el.remove();
  };
  return h('div', { class: 'col' }, h('div', { class: 'row' }, h('h1', { class: 'grow' }, 'Stats'), h('button', { class: 'btn small', onclick: csv }, 'Download list (CSV)'), h('button', { class: 'btn small', onclick: () => runNow('analytics') }, icon('refresh'), 'Refresh')),
    h('div', { class: 'card col' }, h('h2', null, 'Posts per day, last 30 days'), h('div', { class: 'bars', role: 'img', 'aria-label': `Posts per day, total ${per.reduce((x, y) => x + y, 0)}` }, per.map((n, i) => h('div', { style: `height:${Math.max(2, (n / max) * 100)}%`, 'data-t': `${n} on ${days[i].slice(5)}` }))), h('div', { class: 'small muted' }, `Highest day: ${max === 1 && !per.some(Boolean) ? 0 : max}`)),
    accts.length ? h('div', { class: 'grid' }, ['views', 'reach', 'likes', 'comments'].map((k) => h('div', { class: 'card stat' }, h('b', null, (tot[k] || 0).toLocaleString()), h('span', null, `${k} (last 30 posts)`)))) : h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Instagram numbers show up after the first posts. Press Refresh to load them.')),
    best.length ? h('div', { class: 'banner info' }, h('div', null, h('b', null, 'Best times to post: '), best.map((x) => `${((x + 11) % 12) + 1}${x < 12 ? ' am' : ' pm'}`).join(', '), '. Based on reach of your recent posts.')) : null,
    posts.length ? h('div', { class: 'card' }, h('h2', null, 'Top posts'), h('table', { class: 't' }, h('tbody', null, posts.map((p) => h('tr', null, h('td', null, h('a', { href: p.permalink, target: '_blank', rel: 'noopener' }, p.caption || 'Open')), h('td', null, `${p.reach} reach`), h('td', null, `${p.likes} likes`)))))) : null,
    accts.filter((x) => x.error).map((x) => h('div', { class: 'banner warn' }, h('div', null, h('b', null, x.label), ' ', x.error, ' ', x.fix))));
}

export async function logs(S) {
  const month = new Date().toISOString().slice(0, 7), prev = new Date(Date.now() - 31 * 864e5).toISOString().slice(0, 7);
  let text = (await S.data.readText(`logs/${month}.jsonl`)) || ''; if (text.split('\n').length < 40) text = ((await S.data.readText(`logs/${prev}.jsonl`)) || '') + text;
  const ev = text.split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean).reverse().slice(0, 300);
  let only = false; const list = h('div', { class: 'col' });
  const names = Object.fromEntries((S.cfg.routes || []).map((r) => [r.id, r.name]));
  const draw = () => { const l = ev.filter((e) => !only || e.level === 'warn' || e.level === 'error'); list.replaceChildren(...(l.length ? l.map((e) => h('div', { class: 'banner ' + ({ ok: 'ok', warn: 'warn', error: 'bad' }[e.level] || 'info') }, h('div', null, h('div', { class: 'small muted' }, `${fmtDay(e.at, S.tz)} ${fmtTime(e.at, S.tz)}${e.route ? ' · ' + (names[e.route] || e.route) : ''}`.replace(' · ', ', ')), h('div', null, e.msg), e.fix ? h('div', { class: 'small' }, 'What to do: ' + e.fix) : null))) : [h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Nothing to show yet.'))])); };
  draw();
  return h('div', { class: 'col' }, h('div', { class: 'row' }, h('h1', { class: 'grow' }, 'Activity'), h('label', { class: 'switch' }, h('input', { type: 'checkbox', onchange: (e) => { only = e.target.checked; draw(); } }), h('i'), 'Problems only')), list);
}

const ZONES = ['Asia/Kolkata', 'UTC', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Asia/Dubai', 'Asia/Singapore', 'Asia/Tokyo', 'Australia/Sydney'];
export async function settings(S, params, app) {
  const t = S.cfg.notify.telegram, ev = t.events || {};
  const zones = ZONES.includes(S.tz) ? ZONES : [S.tz, ...ZONES];
  const tgRow = (k, label) => h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !!ev[k], onchange: async (e) => { await saveCfg((c) => { c.notify.telegram.events[k] = e.target.checked; }, 'Reelio: alerts'); } }), h('i'), label);
  const theme = (v) => { LS.set('theme', v); if (v === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v; app.rerender(); };
  const backup = async () => {
    const [cfg, led] = await Promise.all([S.data.read('config.json'), S.data.read('ledger.json')]);
    const url = URL.createObjectURL(new Blob([JSON.stringify({ reelio_backup: 1, config: cfg, ledger: led }, null, 1)], { type: 'application/json' }));
    const a = h('a', { href: url, download: 'reelio-backup.json' }); document.body.append(a); a.click(); a.remove();
  };
  return h('div', { class: 'col' }, h('h1', null, 'Settings'),
    h('div', { class: 'card col' }, h('h2', null, 'Time zone'), h('select', { 'aria-label': 'Time zone', onchange: async (e) => { await saveCfg((c) => { c.timezone = e.target.value; }, 'Reelio: time zone'); toast('Saved.'); app.rerender(); } }, zones.map((z) => h('option', { value: z, selected: z === S.tz }, z)))),
    h('div', { class: 'card col' }, h('h2', null, 'How it looks'),
      h('label', { class: 'f' }, 'Text size', h('input', { type: 'range', min: 15, max: 24, step: 1, value: LS.get('fs', 17), oninput: (e) => { LS.set('fs', +e.target.value); document.documentElement.style.setProperty('--fs', e.target.value + 'px'); } })),
      h('div', { class: 'row' }, [['auto', 'Match my device'], ['light', 'Light'], ['dark', 'Dark']].map(([v, l]) => h('button', { class: 'btn small', 'aria-pressed': (LS.get('theme', 'auto') === v) + '', onclick: () => theme(v) }, l)))),
    h('div', { class: 'card col' }, h('h2', null, 'Alerts on Telegram'),
      (S.cfg.connections || []).some((c) => c.kind === 'telegram') ? [h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !!t.enabled, onchange: async (e) => { await saveCfg((c) => { c.notify.telegram.enabled = e.target.checked; }, 'Reelio: alerts'); } }), h('i'), 'Send me alerts'),
        tgRow('posted', 'Every time something is posted'), tgRow('failed', 'When a video fails'), tgRow('limit', 'When Instagram or YouTube slows us down'), tgRow('token', 'When a login is about to expire'), tgRow('daily', 'A summary each evening')]
        : [h('p', { class: 'muted' }, 'Connect Telegram first.'), h('a', { class: 'btn', href: '#/accounts' }, 'Go to Accounts')]),
    h('div', { class: 'card col' }, h('h2', null, 'Backup'), h('p', { class: 'muted' }, 'Saves your flows, settings and the list of everything posted. Logins are not included; they stay locked in your private repository.'),
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: backup }, 'Download backup'),
        h('label', { class: 'btn' }, 'Restore from backup', h('input', { type: 'file', accept: 'application/json', class: 'hide', onchange: async (e) => {
          try { const j = JSON.parse(await e.target.files[0].text()); if (!j.reelio_backup) throw new Error('That is not a Reelio backup.'); if (!confirm('Replace your current flows and settings with this backup?')) return;
            await S.data.update('config.json', () => j.config, 'Reelio: restored backup'); if (j.ledger) await S.data.update('ledger.json', (cur) => ({ ...cur, entries: [...new Map([...(cur.entries || []), ...(j.ledger.entries || [])].map((x) => [x.id, x])).values()] }), 'Reelio: restored ledger'); toast('Restored.'); app.rerender();
          } catch (er) { toast(er.message, 6000); } } })))),
    h('div', { class: 'card col' }, h('h2', null, 'This device'), h('p', { class: 'muted' }, `Using ${S.repo.owner}/${S.repo.app} and the private repository ${S.repo.owner}/${S.repo.data}. Add this page to your home screen to use it like an app.`),
      h('button', { class: 'btn danger', onclick: () => { if (confirm('Sign out of this device? Your flows and data stay safe.')) { LS.del('token'); LS.del('pass'); location.hash = '#/setup'; location.reload(); } } }, 'Sign out of this device')));
}

export async function help(S, params, app) {
  const box = h('div', { class: 'col' });
  const showResult = (d) => box.replaceChildren(d ? h('div', { class: 'col' }, h('div', { class: 'banner ' + (d.ok ? 'ok' : 'warn') }, h('div', null, h('b', null, d.verdict), h('div', { class: 'small' }, 'Checked ' + ago(d.at)))),
    d.checks.map((c) => h('div', { class: 'card flat row' }, h('span', { class: 'pill ' + (c.ok ? 'ok' : 'bad') }, c.ok ? 'OK' : 'Fix'), h('div', { class: 'grow' }, h('b', null, c.title), h('div', { class: 'small muted' }, c.detail), c.fix ? h('div', { class: 'small' }, 'What to do: ' + c.fix) : null)))) : h('p', { class: 'muted' }, 'No check has been run yet.'));
  showResult(await S.data.read('diagnose.json'));
  const btn = h('button', { class: 'btn primary', onclick: async (e) => {
    const b = e.currentTarget, before = ((await S.data.read('diagnose.json')) || {}).at; b.disabled = true; b.replaceChildren(h('span', { class: 'spinner' }), ' Checking, about a minute...');
    try { await S.data.dispatch('diagnose'); } catch (er) { toast(er.message, 7000); b.disabled = false; b.replaceChildren('Why is it failing?'); return; }
    for (let i = 0; i < 30; i++) { await new Promise((r) => setTimeout(r, 6000)); const d = await S.data.read('diagnose.json'); if (d && d.at !== before) { showResult(d); break; } }
    b.disabled = false; b.replaceChildren(icon('check'), 'Check again');
  } }, icon('help'), 'Why is it failing?');
  const faq = (q, a) => h('details', { class: 'card' }, h('summary', null, h('b', null, q)), h('p', { style: 'margin-top:8px' }, a));
  return h('div', { class: 'col' }, h('h1', null, 'Help'), h('p', { class: 'muted' }, 'Press the button. Reelio tests every account and tells you exactly what to fix. It posts nothing.'), btn, box,
    h('h2', { style: 'margin-top:12px' }, 'Quick answers'),
    faq('Nothing is being posted.', 'Check Home: is posting paused? Then check the Schedule: posts only go out between your start and end times. Then press Why is it failing.'),
    faq('It says Instagram asked us to slow down.', 'Instagram limits how fast apps can post. Reelio waits and tries again by itself. If it happens a lot, lower the posts per day in the flow.'),
    faq('Will it ever post the same video twice?', 'No. Every posted video is remembered forever, even if you delete the flow. Only the "Post again" button can repost.'),
    faq('My PC is off. Does it still work?', 'Yes. Everything runs on GitHub\'s servers. Your PC and phone only need to be on when you change settings.'),
    faq('The Instagram login expired.', 'Open Accounts, tap Reconnect on the Instagram account and paste a fresh token. Reelio renews tokens by itself every 3 weeks, so this is rare.'),
    faq('YouTube says it is blocking downloads.', 'YouTube sometimes refuses cloud servers. Add your browser cookies under Accounts, YouTube downloads, or keep the original files in Google Drive and use a Drive flow instead.'));
}
