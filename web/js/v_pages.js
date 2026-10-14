import { h, icon, toast, chip } from './core.js';
import { saveCfg, runNow } from './app.js';

/** One card per Instagram page / YouTube channel, with everything about it in one place and bulk controls over all of its flows. */
export async function pages(S, params, app) {
  const conns = (S.cfg.connections || []).filter((c) => ['instagram', 'youtube'].includes(c.kind) || (S.cfg.routes || []).some((r) => r.target.conn === c.id));
  const routes = S.cfg.routes || [], rs = S.status.routes || {};
  const targets = [...new Set(routes.map((r) => r.target.conn))];
  const list = targets.map((id) => ({ id, conn: (S.cfg.connections || []).find((c) => c.id === id) || { label: id, kind: '' }, flows: routes.filter((r) => r.target.conn === id) }));
  const q = (params[0] || '').toLowerCase();
  const sel = new Set();
  const bulk = h('div', { class: 'bulkbar', hidden: true });
  const drawBulk = () => {
    bulk.hidden = sel.size === 0;
    bulk.replaceChildren(h('b', null, `${sel.size} selected`),
      h('button', { class: 'btn small', onclick: () => apply((r) => { r.enabled = false; }, 'Turned off') }, 'Pause'),
      h('button', { class: 'btn small', onclick: () => apply((r) => { r.enabled = true; }, 'Turned on') }, 'Resume'),
      h('button', { class: 'btn small', onclick: () => { const v = parseInt(prompt('Posts per day for each selected page?', '10'), 10); if (v > 0) apply((r) => { r.schedule.per_day = Math.min(v, 100); }, 'Updated'); } }, 'Posts a day'),
      h('button', { class: 'btn small', onclick: () => { const a = prompt('Start time (HH:MM)', '10:00'), b = a && prompt('End time (HH:MM)', '22:00'); if (/^\d\d:\d\d$/.test(a || '') && /^\d\d:\d\d$/.test(b || '')) apply((r) => { r.schedule.start = a; r.schedule.end = b; }, 'Updated'); } }, 'Time window'),
      h('button', { class: 'btn small', onclick: () => { sel.clear(); app.rerender(); } }, 'Clear'));
  };
  async function apply(fn, msg) {
    try { await saveCfg((c) => { c.routes.forEach((r) => { if (sel.has(r.target.conn)) fn(r); }); }, 'Reelio: bulk change'); toast(`${msg} for ${sel.size} page${sel.size > 1 ? 's' : ''}.`); sel.clear(); app.rerender(); } catch (e) { toast(e.message, 6000); }
  }
  const search = h('input', { type: 'search', placeholder: 'Find a page', 'aria-label': 'Find a page', value: params[0] || '', oninput: (e) => { location.hash = '#/pages/' + encodeURIComponent(e.target.value); } });
  const cards = list.filter((p) => !q || (p.conn.label || '').toLowerCase().includes(q)).map((p) => {
    const st = p.flows.map((f) => rs[f.id] || {}), done = st.reduce((a, s) => a + (s.today_posted || 0), 0), tgt = st.reduce((a, s) => a + (s.today_target || 0), 0);
    const pend = st.reduce((a, s) => a + (s.pending || 0), 0), bad = st.find((s) => s.problem);
    const on = p.flows.some((f) => f.enabled !== false);
    const pill = !on ? h('span', { class: 'pill' }, 'Off') : bad ? h('span', { class: 'pill warn' }, 'Needs a look') : h('span', { class: 'pill ok' }, 'Running');
    return h('div', { class: 'card col page' },
      h('div', { class: 'row' }, h('input', { type: 'checkbox', 'aria-label': 'Select ' + p.conn.label, onchange: (e) => { e.target.checked ? sel.add(p.id) : sel.delete(p.id); drawBulk(); } }), chip(p.conn.label || p.id, p.id), h('div', { class: 'grow' }, h('b', null, p.conn.label || p.id), h('div', { class: 'small muted' }, p.flows[0].target.type === 'youtube' ? 'YouTube channel' : 'Instagram page')), pill),
      h('div', { class: 'meter', role: 'img', 'aria-label': `${done} of ${tgt} posted today` }, h('i', { style: `width:${tgt ? Math.min(100, 100 * done / tgt) : 0}%` })),
      h('div', { class: 'row small muted' }, h('span', null, `${done} of ${tgt} today`), h('span', null, `${pend} waiting`), h('span', null, `${p.flows.length} flow${p.flows.length > 1 ? 's' : ''}`)),
      bad ? h('div', { class: 'errtext' }, bad.problem.msg, h('div', { class: 'small muted' }, bad.problem.fix)) : null,
      h('div', { class: 'row' }, h('a', { class: 'btn small', href: '#/flows/' + p.flows[0].id }, 'Settings'), h('a', { class: 'btn small', href: '#/queue/' + p.flows[0].id }, 'Videos'),
        h('button', { class: 'btn small', onclick: () => runNow('run', p.flows[0].id) }, icon('refresh'), 'Run now')));
  });
  return h('div', { class: 'col' }, h('div', { class: 'row' }, h('h1', { class: 'grow' }, 'Pages & channels'), h('a', { class: 'btn primary', href: '#/flows/new' }, icon('plus'), 'Add')),
    h('p', { class: 'muted' }, 'Every Instagram page and YouTube channel in one place. Tick several to change them together.'),
    list.length > 4 ? search : null, bulk, h('div', { class: 'pagegrid' }, cards.length ? cards : h('div', { class: 'card' }, list.length ? 'No page matches that.' : 'No pages yet. Add an account, then create a flow.')));
}
