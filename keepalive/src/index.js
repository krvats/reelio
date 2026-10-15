// Reelio keep-alive: a free Cloudflare Worker that wakes the GitHub workflows on time.
// Why: GitHub's own "cron" is best-effort. On busy hours it starts runs 15 to 60 minutes late, or skips them.
// This Worker runs on Cloudflare's clock (reliable) and starts the workflow itself, only when it is really needed.

const BUSY = new Set(['queued', 'in_progress', 'waiting', 'requested', 'pending']);

/** Pure decision (unit-tested). runs = newest-first list from the GitHub API. */
export function decide({ runs, nowMs, minGapMin }) {
  const list = Array.isArray(runs) ? runs : [];
  if (list.some((r) => BUSY.has(r.status))) return { start: false, why: 'a run is already queued or working' };
  const last = list[0];
  if (last) {
    const ageMin = (nowMs - Date.parse(last.created_at)) / 60000;
    if (ageMin < minGapMin) return { start: false, why: `last run started ${Math.round(ageMin)} min ago` };
  }
  return { start: true, why: last ? 'no run for a while' : 'no run has ever happened' };
}

async function gh(env, path, opts = {}) {
  return fetch('https://api.github.com' + path, {
    ...opts,
    headers: { Authorization: 'Bearer ' + env.GH_TOKEN, Accept: 'application/vnd.github+json', 'User-Agent': 'reelio-keepalive', 'X-GitHub-Api-Version': '2022-11-28', ...(opts.headers || {}) },
  });
}

async function wake(env, file, minGapMin, inputs) {
  const repo = env.GH_REPO || 'krvats/reelio', ref = env.GH_REF || 'main';
  const res = await gh(env, `/repos/${repo}/actions/workflows/${file}/runs?per_page=5`);
  if (!res.ok) return { file, started: false, error: `could not read runs (${res.status})` };
  const runs = (await res.json()).workflow_runs || [];
  const d = decide({ runs, nowMs: Date.now(), minGapMin });
  if (!d.start) return { file, started: false, why: d.why };
  const body = { ref }; if (inputs) body.inputs = inputs;
  const r = await gh(env, `/repos/${repo}/actions/workflows/${file}/dispatches`, { method: 'POST', body: JSON.stringify(body) });
  if (r.status === 204) return { file, started: true, why: d.why };
  if (r.status === 422 || r.status === 404) {   // workflow disabled by GitHub (60 idle days) or missing: try to switch it back on
    const en = await gh(env, `/repos/${repo}/actions/workflows/${file}/enable`, { method: 'PUT' });
    return { file, started: false, error: `GitHub refused the start (${r.status}); tried to re-enable it (${en.status})` };
  }
  return { file, started: false, error: `GitHub refused the start (${r.status}). Check that GH_TOKEN has "Actions: read and write".` };
}

async function tick(env, cron) {
  const out = [];
  if (cron === '7 * * * *') out.push(await wake(env, 'long.yml', 50));
  else out.push(await wake(env, 'tick.yml', 4.5, { action: 'run', route: '' }));
  console.log(JSON.stringify(out));
  return out;
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(tick(env, event.cron)); },
  // Visiting the Worker address only shows whether it is alive. It never starts anything.
  async fetch(req, env) {
    const repo = env.GH_REPO || 'krvats/reelio';
    const res = await gh(env, `/repos/${repo}/actions/workflows/tick.yml/runs?per_page=1`).catch(() => null);
    const run = res && res.ok ? ((await res.json()).workflow_runs || [])[0] : null;
    return new Response(JSON.stringify({ ok: true, repo, last_run: run ? { status: run.status, conclusion: run.conclusion, started: run.created_at } : null }, null, 1), { headers: { 'content-type': 'application/json' } });
  },
};
