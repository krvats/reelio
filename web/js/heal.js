// Self-heal: if the app is open and the cloud worker has been silent too long (GitHub skipped its schedule),
// start a run automatically. Quiet, rate-limited (once per 10 minutes), never touches your data.
import { LS, toast } from './core.js';

const LATE_MIN = 15, EVERY_MS = 120000, COOLDOWN_MIN = 10;

async function check(S) {
  try {
    if (document.hidden || !S.data || !S.token || !S.cfg) return;
    if (typeof S.data.latestRun !== 'function' || typeof S.data.dispatch !== 'function') return;   // hosted mode has no GitHub runs
    if (S.cfg.paused || !(S.cfg.routes || []).length) return;
    const st = await S.data.read('status.json');
    const fin = st && st.run && st.run.finished ? Date.parse(st.run.finished) : 0;
    const lateMin = fin ? (Date.now() - fin) / 60000 : 999;
    if (lateMin < LATE_MIN) return;
    if (Date.now() - (LS.get('heal_at', 0) || 0) < COOLDOWN_MIN * 60000) return;
    const run = await S.data.latestRun();
    if (run && ['queued', 'in_progress', 'waiting', 'pending'].includes(run.status)) return;   // already on its way
    LS.set('heal_at', Date.now());
    await S.data.dispatch('run', '');
    toast('GitHub was late, so Reelio started a check for you.', 5000);
  } catch { /* healing is a bonus; it must never break the app */ }
}

export function startHeal(S) {
  if (window.__reelioHeal) return;
  window.__reelioHeal = true;
  setTimeout(() => check(S), 20000);
  setInterval(() => check(S), EVERY_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) setTimeout(() => check(S), 3000); });
}
