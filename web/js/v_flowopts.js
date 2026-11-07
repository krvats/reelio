// Extra flow settings: mix of pages, "which videos and in what order", and the overlay (layers) editor.
import { h, toast, uid } from './core.js';

const field = (label, input, hint) => h('label', { class: 'f' }, label, hint ? h('small', null, hint) : null, input);
const num = (get, set, o = {}) => h('input', { type: 'number', min: o.min, max: o.max, step: o.step || 1, value: get() ?? '', placeholder: o.ph || '', oninput: (e) => set(e.target.value === '' ? null : +e.target.value) });
const sel = (opts, get, set) => h('select', { onchange: (e) => set(e.target.value) }, opts.map(([v, l]) => h('option', { value: v, selected: get() === v }, l)));
const hex = (v, d) => (/^#[0-9a-f]{6}$/i.test(v || '') ? v : d);
const color = (get, set, d) => h('input', { type: 'color', value: hex(get(), d), oninput: (e) => set(e.target.value) });

/* ---------- several pages + own links ---------- */
export function mixBox(r, redraw) {
  const s = r.source; s.sources = s.sources || [{ type: 'page', url: '', max_items: 50, backlog: 'all' }]; s.net_conn = s.net_conn || 'youtube-net';
  const rows = s.sources.map((c, i) => c.type === 'links'
    ? h('div', { class: 'card col' }, h('b', null, 'My own video links'), h('p', { class: 'small muted' }, 'The links you add on the Videos page are mixed in too.'), h('button', { type: 'button', class: 'btn small', onclick: () => { s.sources.splice(i, 1); redraw(); } }, 'Remove'))
    : h('div', { class: 'card col' },
      field(`Page ${i + 1}`, h('input', { type: 'url', value: c.url || '', placeholder: 'https://www.instagram.com/somepage/', oninput: (e) => { c.url = e.target.value.trim(); } })),
      h('div', { class: 'row' },
        h('div', { class: 'grow' }, field('Read the latest', sel([[25, '25'], [50, '50'], [100, '100'], [200, '200'], [500, '500']].map(([a, b]) => [String(a), b]), () => String(c.max_items || 50), (v) => { c.max_items = +v; }))),
        h('div', { class: 'grow' }, field('Which videos', sel([['all', 'All of them'], ['new', 'Only new ones']], () => c.backlog || 'all', (v) => { c.backlog = v; })))),
      s.sources.length > 1 ? h('button', { type: 'button', class: 'btn small', onclick: () => { s.sources.splice(i, 1); redraw(); } }, 'Remove this page') : null));
  return h('div', { class: 'col' },
    h('p', { class: 'muted' }, 'Add as many pages as you like. Reelio reads each one on its own, so if one page is blocked the others still work. Choose "Take turns between my pages" below to post from them one after the other.'),
    ...rows,
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'btn', onclick: () => { if (s.sources.filter((x) => x.type === 'page').length >= 12) return toast('12 pages is the most.'); s.sources.push({ type: 'page', url: '', max_items: 50, backlog: 'all' }); redraw(); } }, 'Add another page'),
      s.sources.some((c) => c.type === 'links') ? null : h('button', { type: 'button', class: 'btn', onclick: () => { s.sources.push({ type: 'links' }); redraw(); } }, 'Also use my own video links')),
    h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: !!s.rights, onchange: (e) => { s.rights = e.target.checked; } }), 'These pages are mine, or I have permission to reuse their videos.'),
    h('p', { class: 'small muted' }, 'Instagram needs a logged-in cookies.txt (Accounts > YouTube downloads, use a spare login). Views and dates are only known when Reelio can read them from the page; videos without them are put last when you sort.'));
}

export function checkMix(r) {
  if (r.source.type !== 'multi') return '';
  const pages = (r.source.sources || []).filter((c) => c.type === 'page');
  if (!pages.length && !(r.source.sources || []).some((c) => c.type === 'links')) return 'Add at least one page link.';
  if (pages.some((c) => !/^https?:\/\//.test(c.url || ''))) return 'Every page needs a link that starts with https://';
  if (!r.source.rights) return 'Please confirm you own these pages or have permission to reuse their videos.';
  return '';
}

/* ---------- which videos, in what order ---------- */
export const ORDERS = [['oldest', 'Oldest first'], ['newest', 'Newest first'], ['views_high', 'Most views first'], ['views_low', 'Fewest views first'], ['likes_high', 'Most likes first'],
  ['posted_new', 'Newest posted on the page first'], ['posted_old', 'Oldest posted on the page first'], ['mix', 'Take turns between my pages'], ['random', 'Random'], ['manual', 'The order I set']];

export function pickCard(r) {
  const f = (r.filters = r.filters || {});
  const set = (k) => (v) => { if (v === null || v === '' || v === 0 || v === false) delete f[k]; else f[k] = v; };
  const n = (k, o) => num(() => f[k], set(k), o);
  return h('details', { class: 'card', open: !!Object.keys(f).length || ['views_high', 'views_low', 'likes_high', 'posted_new', 'posted_old', 'mix'].includes(r.order) },
    h('summary', null, h('b', null, 'Which videos, and in what order?')),
    h('div', { class: 'col', style: 'margin-top:12px' },
      field('Order', sel(ORDERS, () => r.order || 'oldest', (v) => { r.order = v; })),
      h('p', { class: 'small muted' }, 'Views, likes and dates come from the page when Reelio can read them. A video with no number yet goes last, so it never blocks the others.'),
      h('b', null, 'Only post videos that match'),
      h('div', { class: 'row' }, h('div', { class: 'grow' }, field('At least this many views', n('min_views', { min: 0, ph: 'Any' }))), h('div', { class: 'grow' }, field('At most this many views', n('max_views', { min: 0, ph: 'Any' })))),
      field('At least this many likes', n('min_likes', { min: 0, ph: 'Any' })),
      h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Posted in the last (days)', n('within_days', { min: 1, ph: 'Any' }))), h('div', { class: 'grow' }, field('Posted more than (days) ago', n('older_than_days', { min: 1, ph: 'Any' })))),
      h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Posted from', h('input', { type: 'date', value: (f.date_from || '').slice(0, 10), oninput: (e) => set('date_from')(e.target.value) }))), h('div', { class: 'grow' }, field('Posted until', h('input', { type: 'date', value: (f.date_to || '').slice(0, 10), oninput: (e) => set('date_to')(e.target.value) })))),
      h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Shortest (seconds)', n('min_seconds', { min: 0, ph: 'Any' }))), h('div', { class: 'grow' }, field('Longest (seconds)', n('max_seconds', { min: 0, ph: 'Any' })))),
      field('Caption or title must have one of these words', h('input', { type: 'text', value: f.include || '', placeholder: 'funny, cat', oninput: (e) => set('include')(e.target.value) }), 'Separate words with commas.'),
      field('Skip videos that have these words', h('input', { type: 'text', value: f.exclude || '', placeholder: 'ad, sponsored', oninput: (e) => set('exclude')(e.target.value) })),
      field('Videos where the number or date is not known', sel([['allow', 'Still allow them'], ['skip', 'Skip them']], () => f.unknown || 'allow', (v) => { if (v === 'allow') delete f.unknown; else f.unknown = v; })),
      h('p', { class: 'small muted' }, 'Videos you tick "Post first" on always go out, whatever the filters say.')));
}

/* ---------- overlays ---------- */
const FONT_LIST = [['sans-bold', 'Sans bold'], ['sans', 'Sans'], ['serif-bold', 'Serif bold'], ['mono-bold', 'Typewriter'], ['clean-bold', 'Clean bold'], ['clean-serif', 'Clean serif'], ['narrow-bold', 'Narrow bold'], ['rounded-bold', 'Rounded'], ['hindi', 'Hindi (Devanagari)'], ['custom', 'My own font (link to a .ttf file)']];
const FONT_CSS = { 'sans-bold': 'bold 1em system-ui', sans: '1em system-ui', 'serif-bold': 'bold 1em Georgia,serif', 'mono-bold': 'bold 1em ui-monospace,monospace', 'clean-bold': 'bold 1em system-ui', 'clean-serif': '1em Georgia,serif', 'narrow-bold': 'bold 1em "Arial Narrow",system-ui', 'rounded-bold': 'bold 1em "Trebuchet MS",system-ui', hindi: 'bold 1em system-ui', custom: 'bold 1em system-ui' };
const NEW = {
  text: () => ({ id: 't' + uid().slice(0, 4), type: 'text', text: 'Your text', font: 'sans-bold', size: 90, color: '#ffffff', x: 50, y: 85, wrap: 80, align: 'center', stroke: { w: 0, color: '#000000' }, shadow: { x: 0, y: 0, color: '#000000', opacity: 0.6 }, box: { on: false, color: '#000000', opacity: 0.5, pad: 16 } }),
  image: () => ({ id: 'i' + uid().slice(0, 4), type: 'image', src: '', x: 50, y: 50, w: 30, rotate: 0, opacity: 1 }),
  frame: () => ({ id: 'f' + uid().slice(0, 4), type: 'frame', color: '#ffffff', radius: 40, window: { x: 50, y: 50, w: 86, h: 56 } }),
  box: () => ({ id: 'b' + uid().slice(0, 4), type: 'box', color: '#000000', x: 50, y: 50, w: 100, h: 10, opacity: 0.6 }),
};
const NAME = { text: 'Text', image: 'Picture', frame: 'White part with a see-through window', box: 'Colour box' };

export function overlayCard(S, r) {
  const e = (r.edit = r.edit || {}); e.layers = e.layers || []; e.canvas = e.canvas || { bg: '#000000' };
  const list = h('div', { class: 'col' }), pre = h('div', { class: 'ovprev', role: 'img', 'aria-label': 'Approximate overlay preview' }), videoBox = h('div', { class: 'col' });
  let vid = null, vurl = '', at = 0, sel_ = null;      // a sample video from THIS device, only used for the preview: never uploaded or saved
  const timeBox = h('div', { class: 'col' });
  const L = e.layers;
  const move = (i, d) => { const j = i + d; if (j < 0 || j >= L.length) return; [L[i], L[j]] = [L[j], L[i]]; draw(); };

  function grab(el, l) {      // drag a layer in the picture to move it; tap it to open its settings
    el.style.cursor = 'move'; el.style.touchAction = 'none'; el.style.pointerEvents = 'auto';
    if (l === sel_) el.style.outline = '2px dashed #ff9f1a';
    el.addEventListener('pointerdown', (ev) => {
      ev.preventDefault(); const r0 = pre.getBoundingClientRect(), x0 = ev.clientX, y0 = ev.clientY, lx = l.x, ly = l.y; let moved = false;
      const mv = (m) => { if (Math.abs(m.clientX - x0) + Math.abs(m.clientY - y0) > 4) moved = true; if (!moved) return; l.x = Math.round((lx + (m.clientX - x0) / r0.width * 100) * 10) / 10; l.y = Math.round((ly + (m.clientY - y0) / r0.height * 100) * 10) / 10; preview(); };
      const up = () => { document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); sel_ = l; L.forEach((x) => { x._open = x === l; }); draw(); };
      document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
    });
  }
  function preview() {
    const pct = (v) => v + '%', kids = [];
    const box = e.reel_box;
    const reel = h('div', { class: 'ovreel' }, vid || 'your video');
    if (box) Object.assign(reel.style, { left: pct(box.x - box.w / 2), top: pct(box.y - box.h / 2), width: pct(box.w), height: pct(box.h) }); else Object.assign(reel.style, { left: 0, top: 0, width: '100%', height: '100%' });
    kids.push(reel);
    const frames = {};
    for (const l of L) if (l.type === 'frame') {
      const w = l.window || {}, fr = h('div', { class: 'ovlayer', style: `inset:0;overflow:hidden;pointer-events:none;opacity:${l.opacity ?? 1}` });
      const win = h('div', { style: `position:absolute;left:${w.x - w.w / 2}%;top:${w.y - w.h / 2}%;width:${w.w}%;height:${w.h}%;border-radius:${(l.radius || 0) / 8}px;box-shadow:0 0 0 999px ${hex(l.color, '#ffffff')};overflow:hidden` });
      fr.append(win); frames[l.id] = win; kids.push(fr);
    }
    const W = 260;
    const live = (l) => !vid || ((l.start || 0) <= at && (!l.end || at <= l.end));
    for (const l of L) {
      if (l.type === 'frame' || !live(l)) continue;
      const st = `left:${l.x}%;top:${l.y}%;transform:translate(-50%,-50%) rotate(${l.rotate || 0}deg);opacity:${l.opacity ?? 1};`;
      let el;
      if (l.type === 'box') el = h('div', { class: 'ovlayer', style: st + `width:${l.w}%;height:${l.h}%;background:${hex(l.color, '#000000')}` });
      else if (l.type === 'image') { el = h('div', { class: 'ovlayer ovimg', style: st + `width:${l.w}%;aspect-ratio:1` }, l.src ? 'picture' : 'no picture yet'); }
      else {
        const px = Math.max(6, (l.size || 64) * W / 1080), b = l.box || {}, sh = l.shadow || {}, sk = l.stroke || {};
        el = h('div', { class: 'ovlayer', style: st + `width:${l.wrap || 80}%;text-align:${l.align || 'center'};color:${hex(l.color, '#ffffff')};font:${FONT_CSS[l.font] || FONT_CSS['sans-bold']};font-size:${px}px;line-height:1.15;${b.on ? `background:${hex(b.color, '#000')}${Math.round((b.opacity ?? .5) * 255).toString(16).padStart(2, '0')};padding:${(b.pad || 0) / 5}px;` : ''}${sk.w ? `-webkit-text-stroke:${sk.w / 5}px ${hex(sk.color, '#000')};paint-order:stroke fill;` : ''}${sh.x || sh.y ? `text-shadow:${sh.x / 4}px ${sh.y / 4}px 0 ${hex(sh.color, '#000')};` : ''}` }, (l.text || '').replace(/\{(\w+)\}/g, (m, k) => ({ title: 'Video title', n: '7', date: '5 Nov', author: '@page', views: '12k', likes: '800' }[k] ?? m)));
        grab(el, l);
        if (l.clip_to && frames[l.clip_to]) { const wr = frames[l.clip_to]; const wb = L.find((f) => f.id === l.clip_to).window; el.style.left = ((l.x - (wb.x - wb.w / 2)) / wb.w * 100) + '%'; el.style.top = ((l.y - (wb.y - wb.h / 2)) / wb.h * 100) + '%'; wr.append(el); continue; }
      }
      if (l.type !== 'text') grab(el, l);
      kids.push(el);
    }
    pre.replaceChildren(...kids); pre.style.background = hex(e.canvas.bg, '#000000');
  }

  function layerEditor(l, i) {
    const b = (k, v) => (l[k] = l[k] || v);
    const common = [h('div', { class: 'row' },
      h('div', { class: 'grow' }, field('Show from (seconds)', num(() => l.start || 0, (v) => { l.start = v || 0; }, { min: 0 }))),
      h('div', { class: 'grow' }, field('Hide at (seconds, 0 = until the end)', num(() => l.end || 0, (v) => { l.end = v || 0; }, { min: 0 })))),
    field('See-through amount', h('input', { type: 'range', min: 0.1, max: 1, step: 0.05, value: l.opacity ?? 1, oninput: (ev) => { l.opacity = +ev.target.value; preview(); } }))];
    let body = [];
    if (l.type === 'frame') {
      const w = b('window', { x: 50, y: 50, w: 80, h: 50 });
      const wn = (k, label) => h('div', { class: 'grow' }, field(label, num(() => w[k], (v) => { w[k] = v ?? w[k]; if (l.fitReel) e.reel_box = { ...w, fit: 'cover' }; preview(); }, { min: 1, max: 100 })));
      body = [field('Colour of the part around the window', color(() => l.color, (v) => { l.color = v; preview(); }, '#ffffff')),
        h('div', { class: 'row' }, wn('x', 'Window centre across %'), wn('y', 'Window centre down %')), h('div', { class: 'row' }, wn('w', 'Window width %'), wn('h', 'Window height %')),
        field('Round the window corners', num(() => l.radius || 0, (v) => { l.radius = v || 0; preview(); }, { min: 0, max: 400 })),
        h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: !!e.reel_box, onchange: (ev) => { l.fitReel = ev.target.checked; e.reel_box = ev.target.checked ? { ...w, fit: 'cover' } : undefined; if (!ev.target.checked) delete e.reel_box; draw(); } }), 'Show the video only inside this window (the video sits below, the white part above it)'),
        h('p', { class: 'small muted' }, 'Text layers placed later can be set to show only inside the window.')];
    } else if (l.type === 'box') {
      body = [field('Colour', color(() => l.color, (v) => { l.color = v; preview(); }, '#000000')),
        h('div', { class: 'row' }, ...[['x', 'Centre across %'], ['y', 'Centre down %'], ['w', 'Width %'], ['h', 'Height %']].map(([k, t]) => h('div', { class: 'grow' }, field(t, num(() => l[k], (v) => { l[k] = v ?? l[k]; preview(); }, { min: -50, max: 200 })))))];
    } else if (l.type === 'image') {
      const up = h('input', { type: 'file', accept: 'image/png,image/webp,image/jpeg', class: 'hide', onchange: async (ev) => {
        const f = ev.target.files[0]; if (!f) return;
        if (f.size > 4e6) return toast('Please use a picture under 4 MB.', 5000);
        const bin = Array.from(new Uint8Array(await f.arrayBuffer()), (c) => String.fromCharCode(c)).join('');
        const name = `${uid()}-${f.name.replace(/[^\w.\-]/g, '_')}`;
        try { await S.data.put(`assets/${name}`, btoa(bin), 'Reelio: overlay picture', null, true); l.src = 'asset:' + name; toast('Picture saved.'); draw(); } catch (er) { toast(er.message, 6000); }
      } });
      body = [h('div', { class: 'row' }, h('label', { class: 'btn small' }, l.src ? 'Change picture' : 'Choose a picture (PNG keeps see-through parts)', up), l.src ? h('span', { class: 'small muted' }, 'Picture is set.') : null),
        field('Or a link to a picture', h('input', { type: 'url', value: /^https:/.test(l.src || '') ? l.src : '', placeholder: 'https://...', oninput: (ev) => { l.src = ev.target.value.trim(); } })),
        h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: !!l.full, onchange: (ev) => { l.full = ev.target.checked; preview(); } }), 'Stretch over the whole screen (use for a ready-made frame picture)'),
        h('div', { class: 'row' }, ...[['x', 'Centre across %'], ['y', 'Centre down %'], ['w', 'Width %'], ['rotate', 'Turn (degrees)']].map(([k, t]) => h('div', { class: 'grow' }, field(t, num(() => l[k], (v) => { l[k] = v ?? 0; preview(); }, { min: -360, max: 360 })))))];
    } else {
      const frames = L.filter((x) => x.type === 'frame'), st = b('stroke', { w: 0, color: '#000000' }), sh = b('shadow', { x: 0, y: 0, color: '#000000', opacity: 0.6 }), bx = b('box', { on: false, color: '#000000', opacity: 0.5, pad: 16 });
      body = [field('Text', h('textarea', { oninput: (ev) => { l.text = ev.target.value; preview(); } }, l.text || ''), 'You can use {title} {n} {date} {author} {views} {likes}. They are filled in for every video.'),
        field('Font', sel(FONT_LIST, () => l.font || 'sans-bold', (v) => { l.font = v; draw(); })),
        l.font === 'custom' ? field('Link to the font file (.ttf or .otf)', h('input', { type: 'url', value: l.font_src || '', placeholder: 'https://...', oninput: (ev) => { l.font_src = ev.target.value.trim(); } })) : null,
        h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Size', num(() => l.size, (v) => { l.size = v || 64; preview(); }, { min: 12, max: 400 }))), h('div', { class: 'grow' }, field('Colour', color(() => l.color, (v) => { l.color = v; preview(); }, '#ffffff')))),
        h('div', { class: 'row' }, ...[['x', 'Centre across %'], ['y', 'Centre down %'], ['wrap', 'Line width %']].map(([k, t]) => h('div', { class: 'grow' }, field(t, num(() => l[k], (v) => { l[k] = v ?? l[k]; preview(); }, { min: -50, max: 150 }))))),
        h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Line up', sel([['left', 'Left'], ['center', 'Middle'], ['right', 'Right']], () => l.align || 'center', (v) => { l.align = v; preview(); }))), h('div', { class: 'grow' }, field('Space between lines', num(() => l.spacing ?? 8, (v) => { l.spacing = v ?? 8; }, { min: -20, max: 100 })))),
        h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Outline thickness', num(() => st.w, (v) => { st.w = v || 0; preview(); }, { min: 0, max: 30 }))), h('div', { class: 'grow' }, field('Outline colour', color(() => st.color, (v) => { st.color = v; preview(); }, '#000000')))),
        h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Shadow across', num(() => sh.x, (v) => { sh.x = v || 0; preview(); }, { min: -30, max: 30 }))), h('div', { class: 'grow' }, field('Shadow down', num(() => sh.y, (v) => { sh.y = v || 0; preview(); }, { min: -30, max: 30 }))), h('div', { class: 'grow' }, field('Shadow colour', color(() => sh.color, (v) => { sh.color = v; preview(); }, '#000000')))),
        h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: !!bx.on, onchange: (ev) => { bx.on = ev.target.checked; preview(); } }), 'Coloured strip behind the text'),
        bx.on ? h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Strip colour', color(() => bx.color, (v) => { bx.color = v; preview(); }, '#000000'))), h('div', { class: 'grow' }, field('Strip see-through', h('input', { type: 'range', min: 0.1, max: 1, step: 0.05, value: bx.opacity ?? 0.5, oninput: (ev) => { bx.opacity = +ev.target.value; preview(); } })))) : null,
        h('div', { class: 'row' }, h('div', { class: 'grow' }, field('Fade in (seconds)', num(() => l.fade_in || 0, (v) => { l.fade_in = v || 0; }, { min: 0, max: 30, step: 0.5 }))), h('div', { class: 'grow' }, field('Fade out (seconds)', num(() => l.fade_out || 0, (v) => { l.fade_out = v || 0; }, { min: 0, max: 30, step: 0.5 })))),
        frames.length ? field('Show this text only inside a window', sel([['', 'No, show it everywhere'], ...frames.map((f) => [f.id, `Yes, only inside the window of "${NAME.frame}" #${L.indexOf(f) + 1}`])], () => l.clip_to || '', (v) => { l.clip_to = v; preview(); }), 'The text is cut off at the window edges. Put the text layer after (above) the white part.') : null];
    }
    return h('details', { class: 'card', open: l._open !== false, ontoggle: (ev) => { l._open = ev.target.open; } },
      h('summary', null, h('b', null, `${i + 1}. ${NAME[l.type]}`), l.type === 'text' ? h('span', { class: 'small muted' }, ' ' + (l.text || '').slice(0, 24)) : null),
      h('div', { class: 'col', style: 'margin-top:10px' }, ...body, ...common,
        h('div', { class: 'row' }, h('button', { type: 'button', class: 'btn small', disabled: i === 0, onclick: () => move(i, -1) }, 'Move down a layer'), h('button', { type: 'button', class: 'btn small', disabled: i === L.length - 1, onclick: () => move(i, 1) }, 'Move up a layer'),
          h('button', { type: 'button', class: 'btn small danger right', onclick: () => { if (l.type === 'frame') delete e.reel_box; L.splice(i, 1); draw(); } }, 'Delete'))));
  }

  function draw() {
    drawVideo();
    list.replaceChildren(L.length ? h('p', { class: 'small muted' }, 'Bottom of the list = underneath. Your video is at the very bottom, then each layer is stacked on top of it, so the last one is the top.') : h('p', { class: 'muted' }, 'No overlays yet. Add one below.'), ...L.map(layerEditor));
    preview();
  }
  function drawVideo() {
    const box = e.reel_box, num2 = (k, t) => h('div', { class: 'grow' }, field(t, num(() => box[k], (v) => { box[k] = v ?? box[k]; preview(); }, { min: 0, max: 100 })));
    const pick = h('input', { type: 'file', accept: 'video/*', class: 'hide', onchange: (ev) => {
      const f = ev.target.files[0]; if (!f) return; if (vurl) URL.revokeObjectURL(vurl); vurl = URL.createObjectURL(f);
      vid = h('video', { src: vurl, muted: true, loop: true, playsinline: true, style: 'width:100%;height:100%;object-fit:' + ((e.reel_box || {}).fit === 'contain' ? 'contain' : 'cover') });
      vid.muted = true; vid.addEventListener('loadedmetadata', () => { dur = vid.duration || 10; at = 0; drawVideo(); preview(); }); draw();
    } });
    let dur = vid && vid.duration || 10;
    videoBox.replaceChildren(h('div', { class: 'card col' }, h('b', null, 'Your video (the bottom layer)'),
      h('div', { class: 'row' }, h('label', { class: 'btn small' }, vid ? 'Use another sample video' : 'Pick a sample video to see how it will look', pick), h('span', { class: 'small muted' }, 'Stays on this device. It is only for the preview and is never uploaded.')),
      vid ? h('div', { class: 'col' }, h('label', { class: 'f' }, `Look at second ${at.toFixed(1)}`, h('input', { type: 'range', min: 0, max: Math.max(1, vid.duration || 10), step: 0.1, value: at, oninput: (ev) => { at = +ev.target.value; vid.currentTime = at; preview(); drawVideo(); } })),
        h('small', { class: 'muted' }, 'Layers that start later or end earlier appear and disappear as you move this.')) : null,
      field('Where the video goes', sel([['full', 'Fills the whole screen'], ['box', 'Sits inside a box (set the size below)']], () => (box ? 'box' : 'full'), (v) => { if (v === 'box') e.reel_box = { x: 50, y: 50, w: 86, h: 56, fit: 'cover' }; else delete e.reel_box; draw(); })),
      box ? h('div', { class: 'col' }, h('div', { class: 'row' }, num2('x', 'Centre across %'), num2('y', 'Centre down %')), h('div', { class: 'row' }, num2('w', 'Width %'), num2('h', 'Height %')),
        field('If the shape is different', sel([['cover', 'Fill the box (crop the edges)'], ['contain', 'Show all of it (bars if needed)']], () => box.fit || 'cover', (v) => { box.fit = v; if (vid) vid.style.objectFit = v === 'contain' ? 'contain' : 'cover'; preview(); }))) : null,
      h('p', { class: 'small muted' }, 'Tip: drag any text, picture or box in the preview to move it. Tap it to open its settings.')));
  }
  const add = (t) => () => { if (L.length >= 12) return toast('12 layers is the most.'); L.push(NEW[t]()); draw(); };
  const addWindow = () => {
    const fr = NEW.frame(), tx = { ...NEW.text(), clip_to: fr.id, y: 50, x: 50, text: 'Text inside the window', size: 80 };
    L.push(fr, tx); e.reel_box = { ...fr.window, fit: 'cover' }; fr.fitReel = true; draw();
  };
  draw();
  return h('details', { class: 'card', open: L.length > 0 },
    h('summary', null, h('b', null, 'Overlays: text, pictures and frames')),
    h('div', { class: 'col', style: 'margin-top:12px' },
      h('p', { class: 'muted' }, 'Put text, pictures, colour boxes or a white part with a see-through window on top of every video. Layers go bottom to top: video, then the white part, then text.'),
      h('div', { class: 'ovwrap' }, h('div', { class: 'col' }, pre, timeBox), h('div', { class: 'col grow' },
        h('div', { class: 'row gap-s' }, h('button', { type: 'button', class: 'btn small', onclick: add('text') }, '+ Text'), h('button', { type: 'button', class: 'btn small', onclick: add('image') }, '+ Picture'),
          h('button', { type: 'button', class: 'btn small', onclick: add('frame') }, '+ White part with window'), h('button', { type: 'button', class: 'btn small', onclick: add('box') }, '+ Colour box')),
        h('button', { type: 'button', class: 'btn', onclick: addWindow }, 'Quick start: video in a window with text inside it'),
        field('Background colour behind everything', color(() => e.canvas.bg, (v) => { e.canvas.bg = v; preview(); }, '#000000')),
        h('p', { class: 'small muted' }, 'The picture is only a rough guide. Fonts and exact sizes are drawn by the cloud when posting.'))),
      videoBox, list));
}

