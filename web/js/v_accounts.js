import { h, icon, toast, uid, slug, ago } from './core.js';
import { S as GS, saveCfg, saveSecret, deleteSecret, readSecret, runNow } from './app.js';

const KINDS = {
  instagram: { name: 'Instagram', sub: 'Post Reels to your account', secret: ['access_token'] },
  google: { name: 'Google', sub: 'Drive folders and YouTube', secret: ['refresh_token'] },
  cloudinary: { name: 'Cloudinary', sub: 'Temporary video host Instagram needs', secret: ['api_secret'] },
  telegram: { name: 'Telegram', sub: 'Alerts on your phone (optional)', secret: ['bot_token'] },
  ytnet: { name: 'YouTube downloads', sub: 'Cookies if YouTube blocks the server (optional)', secret: ['cookies'] },
};
const GOOGLE_SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.readonly';
const YT_ONLY_SCOPES = 'https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.readonly';
const redirectUri = () => location.origin + location.pathname;

function dlg(title, body, actions) {
  const d = h('dialog', null, h('div', { class: 'body' }, h('h2', null, title), body, h('div', { class: 'row' }, actions(() => { d.close(); d.remove(); }))));
  d.addEventListener('cancel', () => d.remove()); document.body.append(d); d.showModal(); return d;
}
const inp = (id, label, props = {}, hint) => h('label', { class: 'f' }, label, hint ? h('small', null, hint) : null, h('input', { type: 'text', id, autocomplete: 'off', ...props }));
const val = (id) => document.getElementById(id).value.trim();

export async function accounts(S, params, app) {
  const conns = S.cfg.connections || [], acc = (S.status.accounts || {});
  const needIG = !conns.some((c) => c.kind === 'instagram'), needCl = !conns.some((c) => c.kind === 'cloudinary');
  const cards = conns.map((c) => {
    const a = acc[c.id] || {}, k = KINDS[c.kind] || { name: c.kind };
    const pill = a.problem ? h('span', { class: 'pill ' + (['rate', 'quota'].includes(a.problem.kind) ? 'warn' : 'bad') }, a.problem.kind === 'token' ? 'Login expired' : 'Needs a look')
      : a.connected ? h('span', { class: 'pill ok' }, 'Connected') : h('span', { class: 'pill warn' }, 'Not connected yet');
    const days = a.token_expires ? Math.round((new Date(a.token_expires) - Date.now()) / 86400000) : null;
    return h('div', { class: 'card col' }, h('div', { class: 'row' }, h('div', { class: 'grow' }, h('h2', { style: 'margin:0' }, c.label || k.name), h('div', { class: 'muted small' }, k.name + (c.ig_user_id ? ` (ID ${c.ig_user_id})` : ''))), pill),
      a.problem ? h('div', { class: 'errtext' }, a.problem.msg, h('div', { class: 'small muted' }, a.problem.fix)) : null,
      days != null ? h('div', { class: 'small muted' }, days > 0 ? `Login renews itself. Current one valid for ${days} more days.` : 'Login has expired. Reconnect it.') : null,
      h('div', { class: 'row' }, h('button', { class: 'btn small primary', onclick: () => connect(S, c.kind, c, app) }, a.connected ? 'Reconnect' : 'Connect'),
        h('button', { class: 'btn small danger right', onclick: async () => { if (!confirm(`Remove ${c.label || k.name}? Flows using it will stop until you connect another.`)) return; await saveCfg((cf) => { cf.connections = cf.connections.filter((x) => x.id !== c.id); }, 'Reelio: removed account'); await deleteSecret(c.id).catch(() => {}); app.rerender(); } }, 'Remove')));
  });
  const addBtns = Object.entries(KINDS).map(([k, v]) => h('button', { type: 'button', onclick: () => connect(S, k, null, app) }, h('b', null, v.name), h('span', null, v.sub)));
  return h('div', { class: 'col' }, h('h1', null, 'Accounts'),
    h('p', { class: 'muted' }, 'Connect the places Reelio reads from and posts to. Logins are locked with your passphrase and never shown again.'),
    (needIG || needCl) ? h('div', { class: 'banner info' }, h('div', null, h('b', null, 'To post to Instagram you need: '), [needIG ? 'an Instagram account' : null, needCl ? 'Cloudinary (a free temporary video host)' : null].filter(Boolean).join(' and '), '.')) : null,
    cards, h('div', { class: 'card col' }, h('h2', null, 'Add an account'), h('div', { class: 'choice' }, addBtns)),
    h('div', { class: 'card col' }, h('h2', null, 'Is everything connected?'), h('p', { class: 'muted' }, 'Reelio logs in to each account and tells you exactly what to fix. It posts nothing.'),
      h('button', { class: 'btn', onclick: async () => { await runNow('diagnose'); location.hash = '#/help'; } }, icon('check'), 'Check all connections')));
}

export async function connect(S, kind, existing, app) {
  const label = existing ? existing.label : KINDS[kind].name;
  const id = existing ? existing.id : (kind === 'instagram' ? 'ig_' + uid() : kind === 'ytnet' ? 'youtube-net' : kind === 'google' && !S.cfg.connections.some((c) => c.id === 'google') ? 'google' : kind + (S.cfg.connections.some((c) => c.id === kind) ? '_' + uid() : ''));
  const finish = async (conn, secret, close) => {
    try {
      await saveSecret(conn.id, secret);
      await saveCfg((c) => { const i = c.connections.findIndex((x) => x.id === conn.id); if (i >= 0) c.connections[i] = { ...c.connections[i], ...conn }; else c.connections.push(conn); }, 'Reelio: connected ' + conn.kind);
      close(); toast('Saved. Checking it now.'); runNow('diagnose'); app.rerender();
    } catch (e) { toast(e.message, 7000); }
  };
  if (kind === 'instagram') {
    const body = h('div', { class: 'col' },
      h('ol', { class: 'steps' },
        h('li', null, h('div', null, 'Your Instagram must be a ', h('b', null, 'Professional'), ' account (Creator or Business). In the Instagram app: Settings, Account type and tools, Switch to professional.')),
        h('li', null, h('div', null, 'Open ', h('a', { href: 'https://developers.facebook.com/apps', target: '_blank', rel: 'noopener' }, 'developers.facebook.com/apps'), ', open your app, then ', h('b', null, 'Instagram, API setup with Instagram login'), '.')),
        h('li', null, h('div', null, 'Press ', h('b', null, 'Generate token'), ' next to your account and allow publishing. Copy the token and the account ID shown there.'))),
      inp('f_label', 'A name for this account', { value: existing ? existing.label : '', placeholder: 'For example: snowlves' }),
      inp('f_uid', 'Instagram account ID', { value: existing ? existing.ig_user_id : '', inputmode: 'numeric' }, 'The long number shown next to the token.'),
      inp('f_tok', 'Access token', { type: 'password', placeholder: 'IGAA...' }, existing ? 'Paste a new one to replace the old.' : null));
    return dlg(existing ? 'Reconnect Instagram' : 'Connect Instagram', body, (close) => [
      h('button', { class: 'btn primary', onclick: async () => {
        const tok = val('f_tok'), uidv = val('f_uid'), lab = val('f_label');
        if (!tok && !existing) return toast('Paste the access token.'); if (!uidv) return toast('Paste the account ID.');
        let user = lab; try { const r = await fetch(`https://graph.instagram.com/v21.0/me?fields=user_id,username,account_type&access_token=${encodeURIComponent(tok)}`); const j = await r.json(); if (j.error) return toast('Instagram says: ' + j.error.message, 8000); user = user || j.username; } catch { /* browser cannot check; the server will */ }
        await finish({ id, kind, label: user || 'Instagram', ig_user_id: uidv }, tok ? { access_token: tok, refreshed_at: null, expires_at: null } : {}, close);
      } }, 'Save'), h('button', { class: 'btn', onclick: close }, 'Cancel')]);
  }
  if (kind === 'google') {
    const prev = existing ? await readSecret(id).catch(() => ({})) : {};
    const body = h('div', { class: 'col' },
      h('ol', { class: 'steps' },
        h('li', null, h('div', null, 'Open ', h('a', { href: 'https://console.cloud.google.com/apis/credentials', target: '_blank', rel: 'noopener' }, 'Google Cloud, Credentials'), '. Make a project if asked, then turn on the ', h('b', null, 'Google Drive API'), ' and ', h('b', null, 'YouTube Data API v3'), ' (search for them in the library).')),
        h('li', null, h('div', null, 'On the consent screen, add your own Google address as a test user, and later press ', h('b', null, 'Publish app'), ' so the login does not expire after 7 days.')),
        h('li', null, h('div', null, 'Create credentials, ', h('b', null, 'OAuth client ID'), ', type ', h('b', null, 'Web application'), '. Under Authorized redirect URIs add exactly:', h('div', { class: 'row' }, h('code', { style: 'word-break:break-all' }, redirectUri()), h('button', { class: 'btn small', onclick: () => navigator.clipboard.writeText(redirectUri()).then(() => toast('Copied')) }, 'Copy')))),
        h('li', null, h('div', null, 'Paste the client ID and client secret below, then press Connect.'))),
      inp('f_label', 'A name', { value: existing ? existing.label : 'Google' }),
      inp('f_cid', 'Client ID', { value: prev.client_id || '' }), inp('f_cs', 'Client secret', { type: 'password', value: prev.client_secret || '' }),
      h('label', { class: 'row', style: 'gap:8px;align-items:center' }, h('input', { type: 'checkbox', id: 'f_yt' }), h('span', null, 'This is a YouTube brand channel (no Drive). Use this for Advayu, PK Pujari and similar channels.')));
    return dlg(existing ? 'Reconnect Google' : 'Connect Google', body, (close) => [
      h('button', { class: 'btn primary', onclick: () => {
        const cid = val('f_cid'), cs = val('f_cs'); if (!cid || !cs) return toast('Paste both the client ID and the secret.');
        const state = uid(); sessionStorage.setItem('reelio.oauth', JSON.stringify({ state, id, label: val('f_label') || 'Google', cid, cs }));
        location.href = 'https://accounts.google.com/o/oauth2/v2/auth?' + new URLSearchParams({ client_id: cid, redirect_uri: redirectUri(), response_type: 'code', scope: (document.getElementById('f_yt') && document.getElementById('f_yt').checked) ? YT_ONLY_SCOPES : GOOGLE_SCOPES, access_type: 'offline', prompt: 'consent', state });
      } }, 'Connect with Google'), h('button', { class: 'btn', onclick: close }, 'Cancel')]);
  }
  if (kind === 'cloudinary') {
    const body = h('div', { class: 'col' },
      h('p', null, 'Instagram can only download videos from a public web address, so each video waits on Cloudinary for a minute and is deleted right after posting.'),
      h('ol', { class: 'steps' }, h('li', null, h('div', null, 'Make a free account at ', h('a', { href: 'https://cloudinary.com/users/register_free', target: '_blank', rel: 'noopener' }, 'cloudinary.com'), '.')), h('li', null, h('div', null, 'On the Dashboard press ', h('b', null, 'Go to API Keys'), ' and copy the three values.'))),
      inp('f_cn', 'Cloud name'), inp('f_ak', 'API key'), inp('f_as', 'API secret', { type: 'password' }));
    return dlg('Connect Cloudinary', body, (close) => [h('button', { class: 'btn primary', onclick: () => { const a = [val('f_cn'), val('f_ak'), val('f_as')]; if (a.some((x) => !x)) return toast('Fill in all three.'); finish({ id, kind, label: 'Cloudinary' }, { cloud_name: a[0], api_key: a[1], api_secret: a[2] }, close); } }, 'Save'), h('button', { class: 'btn', onclick: close }, 'Cancel')]);
  }
  if (kind === 'telegram') {
    const body = h('div', { class: 'col' },
      h('ol', { class: 'steps' }, h('li', null, h('div', null, 'In Telegram open ', h('a', { href: 'https://t.me/BotFather', target: '_blank', rel: 'noopener' }, '@BotFather'), ', send /newbot, and copy the token it gives you.')),
        h('li', null, h('div', null, 'Send any message to your new bot. Then open ', h('code', null, 'https://api.telegram.org/bot<token>/getUpdates'), ' and copy the number after "chat":{"id":.'))),
      inp('f_bt', 'Bot token', { type: 'password' }), inp('f_ci', 'Chat ID'));
    return dlg('Connect Telegram alerts', body, (close) => [h('button', { class: 'btn primary', onclick: async () => {
      const t = val('f_bt'), c = val('f_ci'); if (!t || !c) return toast('Fill in both.');
      try { await fetch(`https://api.telegram.org/bot${t}/sendMessage`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chat_id: c, text: 'Reelio is connected. You will get alerts here.' }) }); } catch {}
      await finish({ id: 'telegram', kind, label: 'Telegram' }, { bot_token: t, chat_id: c }, close);
      await saveCfg((cf) => { cf.notify.telegram.enabled = true; }, 'Reelio: alerts on');
    } }, 'Save'), h('button', { class: 'btn', onclick: close }, 'Cancel')]);
  }
  if (kind === 'ytnet') {
    const body = h('div', { class: 'col' },
      h('p', null, 'Only needed if YouTube says it is blocking downloads. Export your cookies from a browser where you are signed in (an extension such as "Get cookies.txt LOCALLY") and paste the file here. Treat them like a password.'),
      h('label', { class: 'f' }, 'Cookies (Netscape format)', h('textarea', { id: 'f_ck' })), inp('f_px', 'Proxy address (optional)', { placeholder: 'http://user:pass@host:port' }));
    return dlg('YouTube downloads', body, (close) => [h('button', { class: 'btn primary', onclick: () => { const ck = document.getElementById('f_ck').value.trim(), px = val('f_px'); if (!ck && !px) return toast('Paste cookies or a proxy.'); finish({ id: 'youtube-net', kind, label: 'YouTube downloads' }, { cookies: ck, proxy: px }, close); } }, 'Save'), h('button', { class: 'btn', onclick: close }, 'Cancel')]);
  }
}

/** Runs once at page load when Google sends the person back with ?code=... */
export async function handleOAuth() {
  const q = new URLSearchParams(location.search); if (!q.get('code') && !q.get('error')) return;
  const saved = JSON.parse(sessionStorage.getItem('reelio.oauth') || 'null'); history.replaceState({}, '', location.pathname + '#/accounts');
  if (!saved || q.get('state') !== saved.state) return toast('That Google sign-in could not be matched. Please try again.', 6000);
  if (q.get('error')) return toast('Google sign-in was cancelled.', 5000);
  try {
    const { Data } = await import('./core.js');
    const r = await fetch('https://oauth2.googleapis.com/token', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ code: q.get('code'), client_id: saved.cid, client_secret: saved.cs, redirect_uri: redirectUri(), grant_type: 'authorization_code' }) });
    const j = await r.json();
    if (!j.refresh_token) throw new Error(j.error_description || 'Google did not return a long-lasting login. Remove the app under myaccount.google.com/permissions and connect again.');
    const { S, loadCore } = await import('./app.js'); if (!S.data) { const { Data: D } = await import('./core.js'); S.data = new D(S.repo, S.token); } await loadCore();
    await saveSecret(saved.id, { client_id: saved.cid, client_secret: saved.cs, refresh_token: j.refresh_token });
    await saveCfg((c) => { const conn = { id: saved.id, kind: 'google', label: saved.label }; const i = c.connections.findIndex((x) => x.id === saved.id); if (i >= 0) c.connections[i] = { ...c.connections[i], ...conn }; else c.connections.push(conn); }, 'Reelio: connected Google');
    sessionStorage.removeItem('reelio.oauth'); toast('Google connected.'); runNow('diagnose');
  } catch (e) { toast(e.message, 9000); }
}
