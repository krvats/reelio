import { h, LS, Data, repoInfo, DEFAULT_CONFIG, encryptJson, decryptJson, toast, icon } from './core.js';
import { logo } from './app.js';

const copy = (text) => navigator.clipboard && navigator.clipboard.writeText(text).then(() => toast('Copied'), () => toast('Select the text and copy it'));

export async function render(S, app) {
  const r = S.repo;
  const box = h('div', { class: 'welcome col' });
  const state = { checking: false, result: null, secrets: null, msg: '' };
  const tokenIn = h('input', { type: 'password', id: 'tok', autocomplete: 'off', value: S.token, placeholder: 'github_pat_...' });
  const passIn = h('input', { type: 'password', id: 'pass', autocomplete: 'new-password', value: S.pass, placeholder: 'A phrase you will remember' });
  const ownerIn = h('input', { type: 'text', id: 'owner', value: r.owner, placeholder: 'your GitHub username' });
  const out = h('div', { class: 'col', id: 'checkout' });

  async function check() {
    const repo = { ...r, owner: ownerIn.value.trim() || r.owner };
    if (!tokenIn.value.trim() || !passIn.value) { toast('Fill in both boxes first.'); return; }
    S.repo = repo; S.token = tokenIn.value.trim(); S.pass = passIn.value; S.data = new Data(repo, S.token);
    LS.set('repo', { owner: repo.owner, app: repo.app, data: repo.data, api: repo.api === 'https://api.github.com' ? undefined : repo.api });
    out.replaceChildren(h('div', { class: 'row' }, h('span', { class: 'spinner' }), 'Checking...'));
    let c;
    try { c = await S.data.check(); } catch (e) { out.replaceChildren(h('div', { class: 'banner bad' }, e.message)); return; }
    const rows = [];
    const row = (ok, text, fix) => h('div', { class: 'banner ' + (ok ? 'ok' : 'warn') }, h('b', null, ok ? 'Done' : 'To do'), h('div', null, text, fix ? h('div', { class: 'small' }, fix) : null));
    rows.push(row(c.token, c.token ? `GitHub key works (signed in as ${c.login}).` : 'GitHub does not accept this key.', c.token ? '' : 'Make a new key with the steps above and paste it again.'));
    if (!c.token) { out.replaceChildren(...rows); return; }
    if (!repo.owner) { repo.owner = c.login; S.repo = repo; ownerIn.value = c.login; S.data = new Data(repo, S.token); LS.set('repo', { owner: repo.owner, app: repo.app, data: repo.data }); c = await S.data.check(); }
    rows.push(row(c.appRepo, c.appRepo ? `App repository ${repo.owner}/${repo.app} found.` : `App repository ${repo.owner}/${repo.app} was not found.`, c.appRepo ? '' : 'Check the spelling of your username above.'));
    rows.push(row(c.dataRepo, c.dataRepo ? `Private data repository ${repo.owner}/${repo.data} found.` : `The private data repository ${repo.data} does not exist yet.`,
      c.dataRepo ? '' : null));
    if (!c.dataRepo) {
      rows.push(h('a', { class: 'btn primary', target: '_blank', rel: 'noopener', href: `https://github.com/new?name=${repo.data}&visibility=private&description=Reelio+data` }, `Create ${repo.data} (private)`));
      rows.push(h('button', { class: 'btn', onclick: check }, 'I created it, check again'));
      out.replaceChildren(...rows); return;
    }
    // passphrase must match any existing secrets
    let blob = null;
    try { blob = await S.data.read('secrets.enc.json'); } catch {}
    if (blob && blob.ct) {
      try { await decryptJson(blob, S.pass); rows.push(row(true, 'Passphrase matches your saved logins.')); }
      catch { rows.push(row(false, 'This passphrase does not match the one used before.', 'Type the passphrase you first chose. Changing it means re-entering your accounts.')); out.replaceChildren(...rows); return; }
    }
    if (!c.hasConfig || !blob) {
      rows.push(h('button', { class: 'btn primary', onclick: async () => {
        try {
          if (!c.hasConfig) await S.data.put('config.json', DEFAULT_CONFIG, 'Reelio: starting settings');
          if (!blob) await S.data.put('secrets.enc.json', await encryptJson({}, S.pass), 'Reelio: empty vault');
          toast('Starting files created.'); check();
        } catch (e) { toast(e.message, 6000); }
      } }, 'Create the starting files'));
      rows.push(h('p', { class: 'small muted' }, 'Moving over from the old ig-pipeline or yt-pipeline? Upload the files from reelio-data-seed to the data repository first (GitHub: Add file, Upload files), then check again. Your posted videos are remembered.'));
      out.replaceChildren(...rows); return;
    }
    rows.push(row(true, 'Settings and vault found.'));
    const names = await S.data.listSecretNames().catch(() => null);
    const need = ['DATA_PAT', 'REELIO_KEY'];
    const secUrl = `https://github.com/${repo.owner}/${repo.app}/settings/secrets/actions`;
    const have = names ? need.filter((n) => names.includes(n)) : [];
    rows.push(h('div', { class: 'card flat col' },
      h('h3', null, 'Last step: two secrets in GitHub'),
      h('p', { class: 'small muted' }, names ? `Found: ${have.join(', ') || 'none yet'}.` : 'Reelio cannot see your secrets, so tick them off yourself.'),
      h('ol', { class: 'steps' },
        h('li', null, h('div', null, 'Open the secrets page and press ', h('b', null, 'New repository secret'), '.', h('div', null, h('a', { href: secUrl, target: '_blank', rel: 'noopener' }, 'Open secrets page')))),
        h('li', null, h('div', null, 'Name: ', h('b', null, 'DATA_PAT'), '. Value: the same GitHub key you pasted above.')),
        h('li', null, h('div', null, 'Add another. Name: ', h('b', null, 'REELIO_KEY'), '. Value: your passphrase.'))),
      h('div', { class: 'row' }, h('button', { class: 'btn small', onclick: () => copy('DATA_PAT') }, 'Copy name DATA_PAT'), h('button', { class: 'btn small', onclick: () => copy('REELIO_KEY') }, 'Copy name REELIO_KEY'))));
    LS.set('token', S.token); LS.set('pass', S.pass);
    rows.push(h('button', { class: 'btn primary', onclick: () => { location.hash = '#/accounts'; } }, 'Finish and connect my accounts'));
    out.replaceChildren(...rows);
  }

  box.append(
    h('div', { class: 'row' }, logo('logo-big'), h('div', null, h('h1', null, 'Welcome to Reelio'), h('p', { class: 'muted' }, 'Your videos, posted automatically. Setup takes about 10 minutes, once.'))),
    h('div', { class: 'card col' },
      h('h2', null, '1. Make a GitHub key'),
      h('p', { class: 'muted' }, 'This key lets this page save your settings. It stays in this browser.'),
      h('ol', { class: 'steps' },
        h('li', null, h('div', null, h('a', { href: 'https://github.com/settings/personal-access-tokens/new', target: '_blank', rel: 'noopener' }, 'Open the key page'), ' and name it Reelio.')),
        h('li', null, h('div', null, 'Under Repository access choose ', h('b', null, 'Only select repositories'), ' and pick ', h('b', null, `${r.app}`), ' and ', h('b', null, `${r.data}`), '.')),
        h('li', null, h('div', null, 'Under Permissions, set ', h('b', null, 'Contents'), ' and ', h('b', null, 'Actions'), ' to Read and write (add ', h('b', null, 'Secrets'), ' to Read-only if you like).')),
        h('li', null, h('div', null, 'Press Generate token, copy it and paste it here.'))),
      h('label', { class: 'f' }, 'GitHub key', tokenIn),
      h('label', { class: 'f' }, 'Your GitHub username', h('small', null, 'Filled in automatically when this page runs on github.io'), ownerIn)),
    h('div', { class: 'card col' },
      h('h2', null, '2. Choose a passphrase'),
      h('p', { class: 'muted' }, 'It locks your Instagram and Google logins so nobody else, not even GitHub staff, can read them. Write it down somewhere safe.'),
      h('label', { class: 'f' }, 'Passphrase', passIn)),
    h('button', { class: 'btn primary', onclick: check }, icon('check'), 'Check my setup'),
    out);
  return box;
}
