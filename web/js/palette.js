// Ctrl/Cmd+K (or "/"): jump anywhere, run something, flip a switch. Same words as the rest of the app.
import { h, toast } from './core.js';
import { S, runNow, saveCfg, app } from './app.js';

const go = (hash) => () => { location.hash = hash; };
function commands() {
  const base = [['Home', go('#/home')], ['Pages & channels', go('#/pages')], ['Videos', go('#/queue')], ['Flows', go('#/flows')], ['New flow', go('#/flows/new')], ['Accounts', go('#/accounts')], ['Save videos to Google Drive', go('#/grab')], ['Paste a link and save to Drive', go('#/grab')], ['Schedule', go('#/schedule')], ['Stats', go('#/analytics')], ['Activity', go('#/logs')], ['Settings', go('#/settings')], ['Help', go('#/help')],
    ['Check now (run everything)', () => runNow('run')],
    [S.cfg && S.cfg.paused ? 'Turn posting on' : 'Pause everything', async () => { await saveCfg((c) => { c.paused = !c.paused; }, 'Reelio: pause toggled'); toast('Done.'); app.rerender(); }]];
  for (const r of (S.cfg && S.cfg.routes) || []) { base.push([`Edit flow: ${r.name}`, go('#/flows/' + r.id)], [`Videos in: ${r.name}`, go('#/queue/' + r.id)], [`Run now: ${r.name}`, () => runNow('run', r.id)]); }
  return base;
}
let dlg = null;
export function openPalette() {
  if (dlg || !S.cfg) return;
  const all = commands(); let idx = 0, shown = all;
  const list = h('div', { class: 'plist', role: 'listbox' });
  const input = h('input', { type: 'search', placeholder: 'Type what you want to do', 'aria-label': 'Command', autocomplete: 'off' });
  const draw = () => list.replaceChildren(...shown.slice(0, 9).map(([t, fn], i) => h('button', { class: i === idx ? 'sel' : '', role: 'option', onclick: () => run(fn) }, t)));
  const close = () => { dlg.remove(); dlg = null; };
  const run = (fn) => { close(); Promise.resolve(fn()).catch((e) => toast(e.message, 5000)); };
  input.addEventListener('input', () => { const q = input.value.toLowerCase().split(/\s+/).filter(Boolean); shown = all.filter(([t]) => q.every((w) => t.toLowerCase().includes(w))); idx = 0; draw(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { idx = Math.min(idx + 1, Math.min(shown.length, 9) - 1); draw(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { idx = Math.max(idx - 1, 0); draw(); e.preventDefault(); }
    else if (e.key === 'Enter' && shown[idx]) run(shown[idx][1]);
    else if (e.key === 'Escape') close();
  });
  dlg = h('div', { class: 'palette', onclick: (e) => { if (e.target === dlg) close(); } }, h('div', { class: 'pbox' }, input, list));
  document.body.append(dlg); draw(); input.focus();
}
document.addEventListener('keydown', (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '');
  if ((e.key === 'k' && (e.ctrlKey || e.metaKey)) || (e.key === '/' && !typing)) { e.preventDefault(); openPalette(); }
});
