import { t } from './i18n.js';
import { h, icon, toast, fmtTime, ago } from './core.js';
import { S as _S, saveCfg, runNow, loadCore } from './app.js';

export const refresh = 30000;

function sentence(S) {
  const st = S.status, rs = Object.values(st.routes || {}), routes = S.cfg.routes || [];
  if (!routes.length) return ['Let us make your first flow.', 'A flow moves videos from a place you keep them to a place you post them.'];
  if (S.cfg.paused) return ['Posting is paused.', 'Nothing will be posted until you turn it back on.'];
  const needs = rs.filter((r) => r.state === 'needs_setup'), waiting = rs.filter((r) => r.state === 'cooldown' && r.problem);
  const done = rs.reduce((a, r) => a + (r.today_posted || 0), 0), target = rs.reduce((a, r) => a + (r.today_target || 0), 0);
  const next = rs.map((r) => r.next_slot).filter(Boolean).sort()[0];
  if (needs.length) return ['Almost there.', needs[0].problem ? needs[0].problem.fix || needs[0].problem.msg : 'Connect your accounts to start.'];
  if (waiting.length) return ['Taking a short break.', `${waiting[0].problem.msg} ${waiting[0].problem.fix || ''}`.trim()];
  const t = next ? ` Next post at ${fmtTime(next, S.tz)}.` : '';
  return [done ? 'All good.' : 'Ready and waiting.', `${done} of ${target} posted today.${t}`];
}

export async function home(S, params, app) {
  const st = S.status || {}, routes = S.cfg.routes || [];
  const [head, sub] = sentence(S);
  const rs = st.routes || {};
  const posted = Object.values(rs).reduce((a, r) => a + (r.today_posted || 0), 0);
  const pending = Object.values(rs).reduce((a, r) => a + (r.pending || 0), 0);
  const failed = Object.values(rs).reduce((a, r) => a + (r.failed || 0), 0);
  const ev = (st.recent || []).filter((e) => ['ok', 'warn', 'error'].includes(e.level));
  const rate = ev.length ? Math.round((100 * ev.filter((e) => e.level === 'ok').length) / ev.length) + '%' : 'none yet';

  const toggle = h('button', { class: 'bigtoggle ' + (S.cfg.paused ? 'off' : 'on'), onclick: async (e) => {
    e.target.disabled = true;
    try { await saveCfg((c) => { c.paused = !c.paused; }, 'Reelio: pause toggled'); toast(S.cfg.paused ? 'Paused. Nothing will be posted.' : 'Posting is on.'); app.rerender(); } catch (er) { toast(er.message, 6000); e.target.disabled = false; }
  } }, t(S.cfg.paused ? 'Turn posting on' : 'Pause everything'));

  const checkBtn = h('button', { class: 'btn small', onclick: async (e) => { e.currentTarget.disabled = true; await runNow('run'); setTimeout(() => app.rerender(), 1500); } }, icon('refresh'), t('Check now'));

  const strips = routes.filter((r) => r.enabled !== false && (st.plan || {})[r.id]).map((r) => {
    const slots = st.plan[r.id]; const nextIdx = slots.findIndex((s) => s.state !== 'done');
    return h('div', { class: 'strip' }, h('div', { class: 'name' }, h('span', null, r.name), h('span', null, `${(rs[r.id] || {}).today_posted || 0} of ${slots.length}`)),
      h('div', { class: 'film', role: 'img', 'aria-label': `${r.name}: ${(rs[r.id] || {}).today_posted || 0} of ${slots.length} posted today` },
        slots.map((s, i) => h('span', { class: 'frame ' + s.state + (i === nextIdx ? ' next' : ''), title: fmtTime(s.at, S.tz) }))));
  });

  const hero = h('section', { class: 'hero', 'aria-labelledby': 'hh' },
    h('h1', { id: 'hh' }, head), h('p', null, sub),
    routes.length ? h('div', { class: 'big' }, toggle, checkBtn, h('span', { class: 'small', style: 'color:#b8bfe8' }, st.run ? `Last check ${ago(st.run.finished)}` + (Date.now() - Date.parse(st.run.finished) > 30 * 60000 ? ' (GitHub is running late; tap Check now)' : '') : 'Not checked yet')) : h('div', { class: 'big' }, h('a', { class: 'btn primary', href: '#/flows/new' }, icon('plus'), 'Create a flow')),
    strips);

  const problems = [];
  for (const [id, a] of Object.entries(st.accounts || {})) {
    if (a.problem) problems.push(h('div', { class: 'banner ' + (a.problem.kind === 'rate' || a.problem.kind === 'quota' ? 'warn' : 'bad') },
      h('div', { class: 'grow' }, h('b', null, a.label || id), h('div', null, a.problem.msg), h('div', { class: 'small' }, a.problem.fix)),
      ['token', 'permission', 'setup'].includes(a.problem.kind) ? h('a', { class: 'btn small', href: '#/accounts' }, 'Fix it') :
        h('button', { class: 'btn small', onclick: async () => { await S.data.command({ cmd: 'clear_cooldown', account: id }); await runNow('run'); app.rerender(); } }, 'Try now')));
  }
  for (const [id, r] of Object.entries(rs)) {
    if (r.problem && r.state === 'cooldown' && !Object.values(st.accounts || {}).some((a) => a.problem && a.problem.msg === r.problem.msg))
      problems.push(h('div', { class: 'banner warn' }, h('div', { class: 'grow' }, h('b', null, r.name), h('div', null, r.problem.msg), h('div', { class: 'small' }, r.problem.fix)), h('a', { class: 'btn small', href: '#/help' }, 'Find out why')));
  }

  const todo = st.todo || [];
  const group = (k, title) => { const l = todo.filter((t) => t.kind === k); return l.length ? h('div', null, h('h3', null, title), h('ul', { style: 'margin:.25rem 0 0;padding-left:1.2rem' }, l.map((t) => h('li', null, t.text)))) : null; };

  const conns = S.cfg.connections || [];
  const steps = [[t('Connect an Instagram page or YouTube channel'), conns.some((c) => ['instagram', 'google'].includes(c.kind) && (st.accounts || {})[c.id] && st.accounts[c.id].connected), '#/accounts'],
    [t('Create a flow (where videos come from and go to)'), routes.length > 0, '#/flows/new'],
    [t('Let Reelio check once'), !!st.run, null],
    [t('Get your first post'), Object.values(rs).some((r) => (r.posted_total || 0) > 0 || (r.today_posted || 0) > 0), '#/queue']];
  const left = steps.filter((x) => !x[1]).length;
  const onboard = left ? h('div', { class: 'card col' }, h('h2', null, `${t('Getting started')}: ${steps.length - left} / ${steps.length}`),
    h('div', { class: 'meter' }, h('i', { style: `width:${100 * (steps.length - left) / steps.length}%` })),
    steps.map(([label, ok, href]) => h('div', { class: 'row' }, h('span', { class: 'pill ' + (ok ? 'ok' : '') }, t(ok ? 'Done' : 'To do')), href && !ok ? h('a', { href }, label) : h('span', null, label)))) : null;

  const quick = (() => {
    const inp = h('input', { type: 'url', placeholder: 'Paste a YouTube or Instagram link', 'aria-label': 'Link to save to Drive', style: 'flex:1 1 220px' });
    const go = () => { const v = inp.value.trim(); if (!v) { location.hash = '#/grab'; return; } try { sessionStorage.setItem('reelio.share', v); } catch {} location.hash = '#/grab'; };
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    return h('div', { class: 'card col' }, h('h2', { style: 'margin:0' }, 'Save a video to Drive'),
      h('div', { class: 'row' }, inp, h('button', { class: 'btn primary', onclick: go }, 'Next')));
  })();
  return h('div', { class: 'col' },
    hero, quick, onboard, problems,
    routes.length ? h('div', { class: 'grid' },
      h('div', { class: 'card stat' }, h('b', null, posted), h('span', null, t('posted today'))),
      h('div', { class: 'card stat' }, h('b', null, pending), h('span', null, t('waiting in line'))),
      h('a', { class: 'card stat', href: '#/queue', style: 'text-decoration:none;color:inherit' }, h('b', { style: failed ? 'color:var(--bad)' : '' }, failed), h('span', null, t('need a look'))),
      h('div', { class: 'card stat' }, h('b', null, rate), h('span', null, t('recent success')))) : null,
    todo.length ? h('div', { class: 'card col' }, h('h2', null, t('What is happening')), group('action', 'To do'), group('done', 'Done'), group('pending', 'Coming up')) : null);
}
