import { h, icon, toast, uid, slug, FILTERS } from './core.js';
import { saveCfg, runNow } from './app.js';

const SRC = [['drive', 'Google Drive folder', 'Videos you keep in Drive'], ['youtube', 'YouTube channel', 'Shorts, long videos and lives from a channel you own'], ['instagram', 'My Instagram', 'Videos already on your account'], ['upload', 'Upload here', 'Add videos from this device']];
const DST = [['instagram', 'Instagram Reels', 'Posts as a Reel'], ['youtube', 'YouTube Shorts', 'Uploads as a Short']];

export async function flows(S, params, app) {
  if (params[0]) return editor(S, params[0], app);
  const routes = S.cfg.routes || [], rs = (S.status.routes || {});
  return h('div', { class: 'col' },
    h('div', { class: 'row' }, h('h1', { class: 'grow' }, 'Flows'), h('a', { class: 'btn primary', href: '#/flows/new' }, icon('plus'), 'New flow')),
    h('p', { class: 'muted' }, 'A flow takes videos from one place and posts them to another, on a schedule. You can have as many as you like.'),
    routes.length ? routes.map((r) => {
      const s = rs[r.id] || {}; const dst = DST.find((d) => d[0] === r.target.type)[1], src = (SRC.find((d) => d[0] === r.source.type) || [])[1];
      const pill = r.enabled === false ? h('span', { class: 'pill' }, 'Off') : s.state === 'needs_setup' ? h('span', { class: 'pill warn' }, 'Needs an account') : s.state === 'cooldown' ? h('span', { class: 'pill warn' }, 'Waiting') : s.state === 'paused' ? h('span', { class: 'pill warn' }, 'Paused') : h('span', { class: 'pill ok' }, 'Running');
      return h('div', { class: 'card col' }, h('div', { class: 'row' }, h('h2', { class: 'grow', style: 'margin:0' }, r.name), pill),
        h('p', { class: 'muted', style: 'margin:0' }, `${src} to ${dst}. ${r.schedule.per_day} a day, between ${r.schedule.start} and ${r.schedule.end}.`),
        s.problem ? h('div', { class: 'errtext' }, s.problem.msg, h('div', { class: 'small muted' }, s.problem.fix)) : null,
        h('div', { class: 'row' }, h('a', { class: 'btn small', href: '#/flows/' + r.id }, 'Edit'), h('a', { class: 'btn small', href: '#/queue/' + r.id }, 'See videos'),
          h('label', { class: 'switch right' }, h('input', { type: 'checkbox', checked: r.enabled !== false, 'aria-label': 'Flow on', onchange: async (e) => { await saveCfg((c) => { c.routes.find((x) => x.id === r.id).enabled = e.target.checked; }, 'Reelio: flow toggled'); app.rerender(); } }), h('i'), h('span', { class: 'small' }, 'On'))));
    }) : h('div', { class: 'card col' }, h('h2', null, 'No flows yet'), h('p', null, 'Make your first one. It takes a minute.'), h('a', { class: 'btn primary', href: '#/flows/new' }, 'Create a flow')));
}

function field(label, input, hint) { return h('label', { class: 'f' }, label, hint ? h('small', null, hint) : null, input); }
function choice(opts, cur, onpick) {
  const wrap = h('div', { class: 'choice', role: 'group' });
  const draw = () => wrap.replaceChildren(...opts.map(([k, t, d]) => h('button', { type: 'button', 'aria-pressed': k === cur, onclick: () => { cur = k; onpick(k); draw(); } }, h('b', null, t), h('span', null, d))));
  draw(); return wrap;
}

async function editor(S, id, app) {
  const isNew = id === 'new';
  const old = isNew ? null : (S.cfg.routes || []).find((r) => r.id === id);
  if (!isNew && !old) return h('div', { class: 'card' }, h('p', null, 'That flow no longer exists.'), h('a', { class: 'btn', href: '#/flows' }, 'Back to flows'));
  const r = old ? structuredClone(old) : {
    id: '', name: '', enabled: true, source: { type: 'drive', conn: 'google', folders: [] }, target: { type: 'instagram', conn: '' }, share_to_feed: true,
    schedule: { per_day: 10, start: '10:00', end: '22:00', jitter: 0.25, max_per_run: 10, gap_seconds: 90, scan_every_min: 30 },
    caption: { mode: 'same', text: '', template: '{title}', hashtag_sets: [], variants: [], table: {} }, edit: { filter: 'none', strength: 1, fit: 'keep', audio: { mode: 'keep' }, watermark: {} }, order: 'oldest' };
  const conns = S.cfg.connections || [];
  const ofKind = (k) => conns.filter((c) => c.kind === k);
  const srcBox = h('div', { class: 'col' }), dstBox = h('div', { class: 'col' }), perDayNote = h('p', { class: 'small muted' });

  function drawSrc() {
    const t = r.source.type, kids = [];
    if (t === 'drive') {
      if (!ofKind('google').length) kids.push(h('div', { class: 'banner info' }, 'Connect Google first in Accounts, then come back.'));
      kids.push(field('Drive folder links', h('textarea', { 'aria-label': 'Drive folder links', oninput: (e) => { r.source.folders = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean); } }, (r.source.folders || []).join('\n')), 'Paste one link per line. Folders inside folders are included.'));
      kids.push(field('Google account', h('select', { onchange: (e) => { r.source.conn = e.target.value; } }, (ofKind('google').length ? ofKind('google') : [{ id: 'google', label: 'Google' }]).map((c) => h('option', { value: c.id, selected: c.id === r.source.conn }, c.label)))));
    } else if (t === 'youtube') {
      kids.push(field('Channel', h('input', { type: 'text', value: r.source.handle || '', placeholder: '@yourchannel', oninput: (e) => { r.source.handle = e.target.value.trim(); } }), 'Only use channels you own or have permission to reuse.'));
      const inc = r.source.include || 'shorts';
      kids.push(field('Which videos', h('select', { onchange: (e) => { r.source.include = e.target.value; drawSrc(); } }, [['shorts', 'Shorts only'], ['long', 'Long videos and past live streams only'], ['all', 'Everything on the channel'], ['selected', 'Only videos I pick']].map(([v, l]) => h('option', { value: v, selected: inc === v }, l)))));
      if (inc === 'selected') kids.push(field('Video links', h('textarea', { 'aria-label': 'Video links', placeholder: 'https://www.youtube.com/watch?v=...', oninput: (e) => { r.source.videos_text = e.target.value; } }, r.source.videos_text || (r.source.videos || []).join('\n')), 'One link per line. They are posted in this order.'));
      if (inc !== 'shorts') {
        const c = (r.source.clip = r.source.clip || { enabled: true, seconds: 60, skip_start: 0, skip_end: 0, max_per_video: 0 });
        kids.push(field('Long videos', h('select', { onchange: (e) => { c.enabled = e.target.value === '1'; drawSrc(); } }, [['1', 'Cut into short clips (best for Reels and Shorts)'], ['0', 'Post the whole video (Instagram allows about 15 minutes at most)']].map(([v, l]) => h('option', { value: v, selected: (c.enabled ? '1' : '0') === v }, l)))));
        if (c.enabled) {
          const num = (k, label, hint) => field(label, h('input', { type: 'number', min: 0, value: c[k] || 0, oninput: (e) => { c[k] = Math.max(0, +e.target.value || 0); } }), hint);
          kids.push(num('seconds', 'Length of each clip (seconds)', '60 is a good start. Shorts must stay under 180.'));
          kids.push(num('skip_start', 'Skip the first (seconds)', 'Skips an intro or the waiting screen at the start of a live.'));
          kids.push(num('skip_end', 'Skip the last (seconds)', 'Skips the outro.'));
          kids.push(num('max_per_video', 'Most clips from one video (0 = all)', 'Handy for a 5 hour stream: 0 uses the whole stream. Each clip is downloaded on its own, nothing is stored.'));
        }
      }
      r.source.conn = r.source.conn || (ofKind('google')[0] || {}).id || 'google'; r.source.net_conn = r.source.net_conn || 'youtube-net';
      kids.push(h('p', { class: 'small muted' }, 'YouTube sometimes blocks cloud servers from downloading. If it does, Reelio tells you, and you can add browser cookies in Accounts.'));
    } else if (t === 'instagram') {
      kids.push(field('Instagram account', h('select', { onchange: (e) => { r.source.conn = e.target.value; } }, ofKind('instagram').map((c) => h('option', { value: c.id, selected: c.id === r.source.conn }, c.label)))));
      if (!r.source.conn && ofKind('instagram')[0]) r.source.conn = ofKind('instagram')[0].id;
    } else kids.push(h('p', { class: 'muted' }, 'After saving, open Videos and press Add videos. Each video is removed from storage once it is posted.'));
    if (t === 'youtube' || t === 'instagram') {
      kids.push(field('Backup Drive folder (optional)', h('textarea', { 'aria-label': 'Backup Drive folder links', placeholder: 'https://drive.google.com/drive/folders/...', oninput: (e) => { r.source.backup_folders = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean); } }, (r.source.backup_folders || []).join('\n')),
        'If a video cannot be downloaded, Reelio uses the file from this folder instead. Name the file with the video id shown in Videos (for example ' + (t === 'youtube' ? 'JizoiMeSzvg.mp4' : '17912345678.mp4') + '). If the folder is in the Google account you connected, no sharing is needed. Otherwise share it with that account (Viewer is enough) or set Anyone with the link: Viewer.'));
      r.source.backup_conn = r.source.backup_conn || (ofKind('google')[0] || {}).id || 'google';
    }
    srcBox.replaceChildren(...kids);
  }
  function drawDst() {
    const t = r.target.type, list = t === 'instagram' ? ofKind('instagram') : ofKind('google');
    if (!list.some((c) => c.id === r.target.conn)) r.target.conn = (list[0] || {}).id || '';
    dstBox.replaceChildren(list.length ? field(t === 'instagram' ? 'Instagram account' : 'YouTube channel (Google account)', h('select', { id: 'dst', onchange: (e) => { r.target.conn = e.target.value; } }, list.map((c) => h('option', { value: c.id, selected: c.id === r.target.conn }, c.label))))
      : h('div', { class: 'banner info' }, h('div', null, `No ${t === 'instagram' ? 'Instagram' : 'Google'} account is connected yet. `, h('a', { href: '#/accounts' }, 'Connect one in Accounts'), '.')));
    note();
  }
  function note() {
    const n = +r.schedule.per_day, t = r.target.type;
    perDayNote.textContent = t === 'youtube' && n > 6 ? 'YouTube normally allows only about 6 uploads a day through its API for new projects. Higher numbers will be limited by YouTube.'
      : n > 60 ? 'That is a lot. Instagram may slow or flag busy accounts. Starting lower and building up is safer. The hard limit is 100 a day.' : n >= 1 ? `About one post every ${Math.max(1, Math.round(windowMinutes() / n))} minutes.` : '';
  }
  const mins = (t) => { const [a, b] = (t || '0:0').split(':'); return +a * 60 + +b; };
  const windowMinutes = () => Math.max(60, mins(r.schedule.end) - mins(r.schedule.start));

  const name = h('input', { type: 'text', value: r.name, placeholder: 'For example: Drive to my main account', oninput: (e) => { r.name = e.target.value; } });
  const perDay = h('input', { type: 'number', min: 1, max: 100, value: r.schedule.per_day, oninput: (e) => { r.schedule.per_day = Math.max(1, Math.min(100, +e.target.value || 1)); note(); } });
  const chips = h('div', { class: 'row gap-s' }, [5, 10, 25, 50, 80].map((n) => h('button', { type: 'button', class: 'btn small', onclick: () => { r.schedule.per_day = n; perDay.value = n; note(); } }, String(n))));
  const filterSel = h('select', { onchange: (e) => { r.edit.filter = e.target.value; prev(); } }, Object.entries(FILTERS).map(([k, [l]]) => h('option', { value: k, selected: k === (r.edit.filter || 'none') }, l)));
  const strength = h('input', { type: 'range', min: 0, max: 1.5, step: 0.05, value: r.edit.strength ?? 1, 'aria-label': 'Filter strength', oninput: (e) => { r.edit.strength = +e.target.value; prev(); } });
  const preview = h('div', { class: 'preview', role: 'img', 'aria-label': 'Approximate filter preview' });
  function prev() { const f = (FILTERS[r.edit.filter] || FILTERS.none)[1]; preview.style.filter = f; preview.style.opacity = f === 'none' ? 1 : 0.55 + 0.45 * Math.min(1, (r.edit.strength ?? 1)); }

  const csvIn = h('input', { type: 'file', accept: '.csv,text/csv', class: 'hide', onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return; const t = await f.text(); const table = {}; let n = 0;
    for (const line of t.split(/\r?\n/)) { const m = line.match(/^\s*("([^"]*)"|[^,]*)\s*,\s*(.*)$/); if (!m) continue; const k = (m[2] ?? m[1]).trim(), v = m[3].replace(/^"|"$/g, '').trim(); if (k && k.toLowerCase() !== 'name' && v) { table[k] = v; n++; } }
    r.caption.table = table; toast(`${n} captions loaded.`);
  } });

  const saveBtn = h('button', { class: 'btn primary', onclick: async (e) => {
    if (!r.name.trim()) r.name = `${(SRC.find((s) => s[0] === r.source.type) || [])[1] || 'Videos'} to ${(DST.find((s) => s[0] === r.target.type) || [])[1]}`;
    if (!r.target.conn) return toast('Connect an account for the destination first.', 5000);
    if (r.source.type === 'drive' && !(r.source.folders || []).length) return toast('Paste at least one Drive folder link.', 5000);
    if (r.source.type === 'youtube' && !r.source.handle && r.source.include !== 'selected') return toast('Type the channel name, like @yourchannel.', 5000);
    if (r.source.type === 'youtube' && r.source.include === 'selected' && !(r.source.videos_text || '').trim() && !(r.source.videos || []).length) return toast('Paste at least one video link.', 5000);
    if (r.source.clip && r.source.clip.seconds) r.source.clip.seconds = Math.max(15, Math.min(r.source.clip.seconds, 180));
    if (mins(r.schedule.end) <= mins(r.schedule.start)) return toast('The end time must be after the start time.', 5000);
    e.currentTarget.disabled = true;
    r.caption.hashtag_sets = (r.caption.hashtag_sets || []).filter(Boolean); r.schedule.gap_seconds = Math.max(+r.schedule.gap_seconds || 90, 60);
    try {
      await saveCfg((c) => {
        if (isNew) { let base = slug(r.name), i = 1, idc = base; while (c.routes.some((x) => x.id === idc)) idc = base + '-' + (++i); r.id = idc; c.routes.push(r); }
        else { const i = c.routes.findIndex((x) => x.id === r.id); c.routes[i] = r; }
      }, 'Reelio: saved flow');
      toast('Saved.'); runNow('scan', r.id); location.hash = '#/flows';
    } catch (er) { toast(er.message, 6000); e.currentTarget.disabled = false; }
  } }, 'Save flow');

  drawSrc(); drawDst(); prev();
  const lines = (v) => (v || []).join('\n');
  return h('div', { class: 'col' },
    h('div', { class: 'row' }, h('a', { href: '#/flows' }, 'Back to flows')),
    h('h1', null, isNew ? 'New flow' : 'Edit flow'),
    h('div', { class: 'card col' }, field('Name', name, 'Optional. We will pick one for you.')),
    h('div', { class: 'card col' }, h('h2', null, 'Where do the videos come from?'), choice(SRC, r.source.type, (k) => { r.source = k === 'drive' ? { type: k, conn: (ofKind('google')[0] || {}).id || 'google', folders: [] } : { type: k, conn: r.source.conn }; drawSrc(); }), srcBox),
    h('div', { class: 'card col' }, h('h2', null, 'Where should they be posted?'), choice(DST, r.target.type, (k) => { r.target = { type: k, conn: '' }; drawDst(); }), dstBox),
    h('div', { class: 'card col' }, h('h2', null, 'How often?'),
      field('Posts per day', perDay), chips, perDayNote,
      h('div', { class: 'row' }, h('div', { class: 'grow' }, field('From', h('input', { type: 'time', value: r.schedule.start, onchange: (e) => { r.schedule.start = e.target.value; note(); } }))), h('div', { class: 'grow' }, field('Until', h('input', { type: 'time', value: r.schedule.end, onchange: (e) => { r.schedule.end = e.target.value; note(); } })))),
      h('p', { class: 'small muted' }, `Times use your timezone: ${S.tz}. Change it in Settings.`),
      field('Which video first?', h('select', { onchange: (e) => { r.order = e.target.value; } }, [['oldest', 'Oldest first'], ['newest', 'Newest first'], ['random', 'Random'], ['manual', 'The order I set']].map(([v, l]) => h('option', { value: v, selected: r.order === v }, l)))),
      h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: (r.schedule.jitter ?? 0.25) > 0, onchange: (e) => { r.schedule.jitter = e.target.checked ? 0.25 : 0; } }), h('i'), 'Vary the exact minutes so it looks natural')),
    h('details', { class: 'card', open: true }, h('summary', null, h('b', null, 'Captions')),
      h('div', { class: 'col', style: 'margin-top:12px' },
        field('Caption style', h('select', { onchange: (e) => { r.caption.mode = e.target.value; } }, [['same', 'Same text for every video'], ['original', 'Use the original title and description'], ['filename', 'Use the file name']].map(([v, l]) => h('option', { value: v, selected: r.caption.mode === v }, l)))),
        field('Caption text', h('textarea', { oninput: (e) => { r.caption.text = e.target.value; } }, r.caption.text || ''), 'Emoji are fine. You can use {n} for the post number, {name} for the file name and {date}.'),
        field('Hashtag sets', h('textarea', { oninput: (e) => { r.caption.hashtag_sets = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean); } }, lines(r.caption.hashtag_sets)), 'One set per line. Reelio rotates through them so posts are not identical.'),
        field('Caption variants', h('textarea', { oninput: (e) => { r.caption.variants = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean); } }, lines(r.caption.variants)), 'Optional. One per line; used in turn instead of the single text above.'),
        h('div', { class: 'row' }, h('label', { class: 'btn small' }, 'Import captions from a spreadsheet (CSV)', csvIn), h('span', { class: 'small muted' }, `${Object.keys(r.caption.table || {}).length} saved. Two columns: file name, caption.`)))),
    h('details', { class: 'card' }, h('summary', null, h('b', null, 'Look and sound')),
      h('div', { class: 'col', style: 'margin-top:12px' }, preview, h('p', { class: 'small muted' }, 'Approximate preview. The real filter is applied when posting.'),
        field('Filter', filterSel), field('Strength', strength),
        field('Shape', h('select', { onchange: (e) => { r.edit.fit = e.target.value; } }, [['keep', 'Keep as it is'], ['blur', 'Fill the screen (blurred sides)'], ['crop', 'Fill the screen (crop)'], ['pad', 'Fill the screen (black bars)']].map(([v, l]) => h('option', { value: v, selected: (r.edit.fit || 'keep') === v }, l))), 'Reels look best at tall 9:16.'),
        h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: (r.edit.audio || {}).mode === 'mute', onchange: (e) => { r.edit.audio = { mode: e.target.checked ? 'mute' : 'keep' }; } }), h('i'), 'Remove the sound'),
        field('Watermark text', h('input', { type: 'text', value: (r.edit.watermark || {}).text || '', placeholder: '@myaccount', oninput: (e) => { r.edit.watermark = { ...(r.edit.watermark || {}), text: e.target.value }; } })),
        field('Cover picture at (seconds)', h('input', { type: 'number', min: 0, step: 0.5, value: r.edit.cover_seconds ?? '', placeholder: 'Automatic', oninput: (e) => { r.edit.cover_seconds = e.target.value === '' ? null : +e.target.value; } })))),
    h('div', { class: 'row' }, saveBtn, h('a', { class: 'btn', href: '#/flows' }, 'Cancel'),
      !isNew ? h('button', { class: 'btn danger right', onclick: async () => { if (!confirm('Delete this flow? Videos already posted are still remembered and will not be reposted.')) return; await saveCfg((c) => { c.routes = c.routes.filter((x) => x.id !== r.id); }, 'Reelio: deleted flow'); location.hash = '#/flows'; } }, 'Delete') : null));
}
