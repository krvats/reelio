import { h, icon, toast, fmtDay, ago, FILTERS } from './core.js';
import { saveCfg, runNow } from './app.js';
import { parseLinks } from './links.js';

const TABS = [['pending', 'Waiting'], ['posted', 'Posted'], ['failed', 'Problems'], ['skipped', 'Set aside']];

export async function queue(S, params, app) {
  const routes = S.cfg.routes || [];
  if (!routes.length) return h('div', { class: 'card col' }, h('h1', null, 'Videos'), h('p', null, 'No flows yet, so there are no videos to show.'), h('a', { class: 'btn primary', href: '#/flows/new' }, 'Create a flow'));
  const rid = params[0] && routes.some((r) => r.id === params[0]) ? params[0] : routes[0].id;
  const route = routes.find((r) => r.id === rid);
  const q = (await S.data.read(`queues/${rid}.json`)) || { items: [] };
  let tab = sessionStorage.getItem('qtab') || 'pending', needle = '';
  const list = h('div', { class: 'col' }), tabsEl = h('div', { class: 'tabsbar', role: 'group', 'aria-label': 'Show' });
  const cnt = (k) => q.items.filter((i) => i.status === k || (k === 'skipped' && i.status === 'missing')).length;
  const cmd = async (c, msg) => { try { await S.data.command({ ...c, route: rid }); toast(msg); } catch (e) { toast(e.message, 6000); } };
  const go = async () => { await runNow('run', rid); };

  function itemCard(it, idx, arr) {
    const cap = it.caption_override || '';
    const acts = [];
    const b = (label, fn, cls = '') => h('button', { class: 'btn small ' + cls, onclick: fn }, label);
    if (it.status === 'pending') {
      acts.push(b('Post now', async () => { if (S.cfg.paused) return toast('Posting is paused. Turn it on from Home first.'); await cmd({ cmd: 'post_now', key: it.key }, 'Queued. It posts within a few minutes.'); await go(); }, 'primary'));
      acts.push(b('Move to top', async () => { await cmd({ cmd: 'reorder', keys: [it.key, ...arr.filter((x) => x.key !== it.key).slice(0, 40).map((x) => x.key)] }, 'Moved to the top.'); }));
      acts.push(b('Caption', () => editCaption(it)));
      acts.push(b('Skip', async () => { await cmd({ cmd: 'skip', key: it.key }, 'Set aside.'); it.status = 'skipped'; draw(); }));
    } else if (it.status === 'failed') {
      acts.push(b('Try again', async () => { await cmd({ cmd: 'retry', key: it.key }, 'Will try again on the next check.'); it.status = 'pending'; draw(); }, 'primary'));
      acts.push(b('Skip', async () => { await cmd({ cmd: 'skip', key: it.key }, 'Set aside.'); it.status = 'skipped'; draw(); }));
    } else if (it.status === 'skipped' || it.status === 'missing') {
      acts.push(b('Use again', async () => { await cmd({ cmd: 'unskip', key: it.key }, 'Back in line.'); it.status = 'pending'; draw(); }));
    } else if (it.status === 'posted') {
      if (it.permalink) acts.push(h('a', { class: 'btn small', href: it.permalink, target: '_blank', rel: 'noopener' }, 'Open post'));
      acts.push(b('Post again', async () => { if (confirm('Post this video again? Reelio normally never reposts.')) { await cmd({ cmd: 'repost', key: it.key }, 'Queued again.'); it.status = 'pending'; draw(); } }));
    }
    const thumb = h('div', { class: 'thumb', style: it.thumb ? `background-image:url("${it.thumb.replace(/"/g, '%22')}")` : null }, it.thumb ? null : icon('queue'));
    const el = h('article', { class: 'item', draggable: it.status === 'pending' && tab === 'pending', 'data-key': it.key },
      thumb, h('div', null,
        h('h3', null, it.name || it.key),
        h('div', { class: 'row gap-s small muted' }, it.status === 'posted' ? h('span', { class: 'pill ok' }, 'Posted ' + (it.posted_at ? ago(it.posted_at) : '')) : null,
          it.status === 'failed' ? h('span', { class: 'pill bad' }, 'Problem') : null, it.status === 'missing' ? h('span', { class: 'pill warn' }, 'No longer in the source') : null,
          it.fails && it.status === 'pending' ? h('span', { class: 'pill warn' }, `Tried ${it.fails} time${it.fails > 1 ? 's' : ''}`) : null,
          it.post_now ? h('span', { class: 'pill' }, 'Posting next') : null, cap ? h('span', { class: 'pill' }, 'Own caption') : null),
        it.last_error && it.status !== 'posted' ? h('div', { class: 'errtext' }, it.last_error.msg, it.last_error.fix ? h('div', { class: 'small muted' }, it.last_error.fix) : null) : null,
        it.note ? h('div', { class: 'small muted' }, it.note) : null,
        h('div', { class: 'acts' }, acts)));
    el.addEventListener('dragstart', (e) => { el.classList.add('dragging'); e.dataTransfer.setData('text/plain', it.key); });
    el.addEventListener('dragend', () => el.classList.remove('dragging'));
    el.addEventListener('dragover', (e) => e.preventDefault());
    el.addEventListener('drop', async (e) => {
      e.preventDefault(); const from = e.dataTransfer.getData('text/plain'); if (!from || from === it.key) return;
      const keys = shown().map((x) => x.key).filter((k) => k !== from); keys.splice(keys.indexOf(it.key), 0, from);
      await cmd({ cmd: 'reorder', keys }, 'New order saved.'); keys.forEach((k, n) => { const x = q.items.find((i) => i.key === k); if (x) x.order = n; }); draw();
    });
    return el;
  }
  function editCaption(it) {
    const ta = h('textarea', { id: 'capta' }, it.caption_override || '');
    const dlg = h('dialog', null, h('div', { class: 'body' }, h('h2', null, 'Caption for this video'), h('p', { class: 'muted' }, 'Leave empty to use the flow\'s normal caption.'), ta,
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: async () => { await cmd({ cmd: 'caption', key: it.key, text: ta.value }, 'Caption saved.'); it.caption_override = ta.value || null; dlg.close(); dlg.remove(); draw(); } }, 'Save'),
        h('button', { class: 'btn', onclick: () => { dlg.close(); dlg.remove(); } }, 'Cancel'))));
    document.body.append(dlg); dlg.showModal();
  }
  const shown = () => {
    let a = q.items.filter((i) => (tab === 'skipped' ? i.status === 'skipped' || i.status === 'missing' : i.status === tab));
    if (needle) a = a.filter((i) => (i.name + ' ' + (i.caption_override || '')).toLowerCase().includes(needle));
    if (tab === 'posted') a = a.slice().sort((x, y) => (y.posted_at || '').localeCompare(x.posted_at || ''));
    else if (tab === 'pending') a = a.slice().sort((x, y) => (x.post_now ? 0 : 1) - (y.post_now ? 0 : 1) || (x.order ?? 1e9) - (y.order ?? 1e9) || (route.order === 'newest' ? (y.created || '').localeCompare(x.created || '') : (x.created || '').localeCompare(y.created || '')));
    return a;
  };
  function draw() {
    tabsEl.replaceChildren(...TABS.map(([k, label]) => h('button', { 'aria-pressed': k === tab, onclick: () => { tab = k; sessionStorage.setItem('qtab', k); draw(); } }, `${label} ${cnt(k)}`)));
    const a = shown();
    list.replaceChildren(...(a.length ? a.slice(0, 60).map((it, i) => itemCard(it, i, a)) : [h('div', { class: 'card' }, h('p', { class: 'muted' }, tab === 'pending' ? 'Nothing is waiting. Add videos to the source and they appear here.' : tab === 'failed' ? 'No problems. Nice.' : 'Nothing here.'))]),
      ...(a.length > 60 ? [h('p', { class: 'muted' }, `Showing the first 60 of ${a.length}. Use search to find others.`)] : []));
  }
  draw();
  const picker = h('select', { 'aria-label': 'Flow', onchange: (e) => { location.hash = '#/queue/' + e.target.value; } }, routes.map((r) => h('option', { value: r.id, selected: r.id === rid }, r.name)));
  const search = h('input', { type: 'text', placeholder: 'Search videos', 'aria-label': 'Search videos', oninput: (e) => { needle = e.target.value.toLowerCase(); draw(); } });
  const upload = route.source.type === 'upload' ? h('label', { class: 'btn primary' }, icon('plus'), 'Add videos', h('input', { type: 'file', accept: 'video/*', multiple: true, class: 'hide', onchange: async (e) => {
    for (const f of e.target.files) {
      if (f.size > 90e6) { toast(`${f.name} is over 90 MB. Use Google Drive for big files.`, 6000); continue; }
      const buf = new Uint8Array(await f.arrayBuffer()); let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      try { await S.data.put(`uploads/${rid}/${f.name.replace(/[^\w.\- ]/g, '_')}`, btoa(bin), 'Reelio: added video', null, true); toast(`${f.name} added.`); } catch (er) { toast(er.message, 6000); }
    }
    await S.data.command({ cmd: 'rescan', route: rid }); await runNow('scan', rid);
  } })) : null;
  const addLinks = route.source.type === 'links' ? h('button', { class: 'btn primary', onclick: () => {
    const ta = h('textarea', { rows: 8, placeholder: 'One link per line.\nhttps://www.instagram.com/reel/XXXX/\nhttps://youtube.com/shorts/YYYY | optional caption for this one', 'aria-label': 'Video links' });
    const first = h('input', { type: 'checkbox' }), rights = h('input', { type: 'checkbox' });
    const d = h('dialog', null, h('div', { class: 'body col' }, h('h2', null, 'Add video links'), ta,
      h('label', { class: 'row small' }, first, 'Post these first'),
      h('label', { class: 'row small' }, rights, 'I own these videos or have permission to post them.'),
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => { d.close(); d.remove(); } }, 'Cancel'),
        h('button', { class: 'btn primary', onclick: async () => {
          if (!rights.checked) return toast('Please confirm you have the right to post these videos.', 5000);
          const list = await parseLinks(ta.value); if (!list.length) return toast('No links found. Paste one link per line.', 4000);
          let added = 0, had = 0;
          for (const l of list) {
            const body = JSON.stringify({ url: l.url, caption: l.caption || undefined, post_first: first.checked || undefined, added_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'), rights_confirmed: true });
            try { await S.data.put(`linkq/${rid}/${l.id}.json`, body, 'Reelio: added link', null); added++; } catch (er) { if (er.status === 409) had++; else { toast(er.message, 6000); } }
          }
          d.close(); d.remove(); toast(`${added} added${had ? `, ${had} were already there` : ''}.`);
          if (added) { await S.data.command({ cmd: 'rescan', route: rid }); await runNow('scan', rid); }
        } }, 'Add'))));
    document.body.append(d); d.showModal();
  } }, icon('plus'), 'Add links') : null;
  return h('div', { class: 'col' }, h('div', { class: 'row' }, h('h1', { class: 'grow' }, 'Videos'), upload, addLinks),
    h('div', { class: 'row' }, h('div', { class: 'grow' }, picker), h('div', { class: 'grow' }, search)),
    h('p', { class: 'muted small' }, route.order === 'manual' ? 'Posted in the order you set. Drag a card to change it.' : `Posted ${route.order === 'newest' ? 'newest first' : route.order === 'random' ? 'in random order' : 'oldest first'}. Use "Move to top" to jump the line.`),
    tabsEl, list,
    q.items.some((i) => i.status === 'failed') && tab === 'failed' ? h('button', { class: 'btn', onclick: async () => { await cmd({ cmd: 'retry_all' }, 'All problems will be tried again.'); q.items.forEach((i) => { if (i.status === 'failed') i.status = 'pending'; }); draw(); } }, 'Try all problems again') : null);
}
