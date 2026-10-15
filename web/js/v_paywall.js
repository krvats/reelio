import { t } from './i18n.js';
import { h, toast } from './core.js';
import { logo } from './app.js';
import * as L from './license.js';

/** Full-screen plan picker. Payment unlocks the app by itself: we poll silently, nobody has to "verify" anything. */
export async function paywall(state, onUnlocked) {
  const p = await L.plans().catch(() => ({ plans: {} }));
  const upi = await L.upiInfo().catch(() => ({ enabled: false }));
  let cur = 'INR'; try { cur = /^en-IN|hi/i.test(navigator.language) || /Kolkata/.test(Intl.DateTimeFormat().resolvedOptions().timeZone) ? 'INR' : 'USD'; } catch {}
  const root = h('div', { class: 'paywall' });
  let poll = null;
  const startPolling = () => {
    clearInterval(poll);
    poll = setInterval(async () => { const e = await L.entitlement(); if (e.active) { clearInterval(poll); toast('You are in. Welcome to Reelio!'); onUnlocked(e); } }, 4000);
  };
  const draw = (msg) => {
    const rows = Object.entries(p.plans || {}).map(([id, pl]) => h('div', { class: 'card plan' + (id === 'pro' ? ' best' : '') },
      id === 'pro' ? h('span', { class: 'badge' }, t('Most popular')) : null,
      h('h3', null, pl.name), h('div', { class: 'price' }, cur === 'INR' ? '₹' + pl.price_inr : '$' + pl.price_usd, h('small', null, ' / month')),
      h('ul', null, h('li', null, `${pl.accounts} Instagram pages & YouTube channels`), h('li', null, `${Number(pl.posts_month).toLocaleString()} posts a month`), h('li', null, `${pl.devices} device${pl.devices > 1 ? 's' : ''}`), h('li', null, 'Everything runs while your phone is off')),
      h('button', { class: 'btn primary', onclick: async (e) => {
        e.target.disabled = true;
        try { const url = await L.checkout(id, cur === 'INR' && pl.razorpay_plan ? 'razorpay' : 'stripe'); window.open(url, '_blank'); draw('Finish paying in the new tab. This page opens by itself when it is done.'); startPolling(); }
        catch (err) { toast(err.message, 6000); e.target.disabled = false; }
      } }, 'Choose ' + pl.name)));
    root.replaceChildren(h('div', { class: 'wrap' }, logo('logo big'), h('h1', null, t('Pick a plan to start')), h('p', { class: 'muted' }, msg || 'Cancel any time. Your device is recognised automatically, so there is nothing to type or verify.'),
      h('div', { class: 'plans' }, rows.length ? rows : h('p', null, 'Plans are not available right now. Please try again shortly.')),
      state && state.state === 'offline' ? h('p', { class: 'muted' }, 'You seem to be offline.') : null,
      upi.enabled ? upiCard(upi, p.plans) : null,
      h('details', { class: 'card flat' }, h('summary', null, 'Already paid on another device?'),
        h('div', { class: 'col' }, h('p', { class: 'muted' }, 'On the paid device open Settings → Subscription → "Add another device" to get a short code.'),
          h('input', { id: 'lc', placeholder: 'Code', autocapitalize: 'characters', maxlength: 8 }),
          h('button', { class: 'btn', onclick: async () => { try { await L.linkRedeem(root.querySelector('#lc').value.trim()); const e = await L.entitlement(); if (e.active) onUnlocked(e); } catch (err) { toast(err.message, 6000); } } }, 'Use code')))));
  };
  draw(); startPolling();
  if (new URLSearchParams(location.search).get('paid')) startPolling();
  return root;
}

export async function subscriptionCard(ent) {
  const c = ent && ent.claims;
  const box = h('div', { class: 'card col' }, h('h2', null, t('Subscription')),
    h('p', null, c ? `Plan: ${c.plan} · ${c.st === 'grace' ? 'payment problem, fix it soon' : c.st === 'comped' ? 'free access' : 'active'}` : 'Open mode'),
    c ? h('p', { class: 'muted' }, `Up to ${c.lim.accounts} accounts · ${Number(c.lim.posts_month).toLocaleString()} posts a month`) : null);
  if (!c) return box;
  const out = h('p', { class: 'big-code' });
  box.append(h('div', { class: 'row' },
    h('button', { class: 'btn small', onclick: async () => { try { location.href = await L.portal(); } catch (e) { toast(e.message, 6000); } } }, t('Manage billing')),
    h('button', { class: 'btn small', onclick: async () => { try { out.textContent = 'Code: ' + (await L.linkCreate()) + ' (valid 10 minutes)'; } catch (e) { toast(e.message, 6000); } } }, t('Add another device'))), out);
  return box;
}

let qrLib = null;
const loadQr = () => qrLib || (qrLib = new Promise((res) => { const sc = document.createElement('script'); sc.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcode-generator/1.4.4/qrcode.min.js'; sc.onload = () => res(window.qrcode); sc.onerror = () => res(null); document.head.append(sc); }));

/** Pay by UPI: scan or tap, then paste the reference number. The owner approves it; the app then unlocks by itself. */
function upiCard(info, plans) {
  let plan = plans.pro ? 'pro' : Object.keys(plans)[0]; const box = h('div', { class: 'col' }); const qrBox = h('div', { class: 'qr' }); const msg = h('p', { class: 'muted' });
  const link = () => `upi://pay?pa=${encodeURIComponent(info.vpa)}&pn=${encodeURIComponent(info.name)}&am=${plans[plan].price_inr}&cu=INR&tn=${encodeURIComponent('Reelio ' + plans[plan].name)}`;
  const drawQr = async () => { const q = await loadQr(); qrBox.replaceChildren(); if (!q) { qrBox.append(h('p', { class: 'muted' }, 'QR could not load. Use the button below on your phone.')); return; } const c = q(0, 'M'); c.addData(link()); c.make(); qrBox.innerHTML = c.createSvgTag({ cellSize: 5, margin: 2, scalable: true }); };
  const utr = h('input', { placeholder: 'UPI reference number (UTR)', autocapitalize: 'characters', maxlength: 22, 'aria-label': 'UPI reference number' });
  const sel = h('select', { 'aria-label': 'Plan', onchange: (e) => { plan = e.target.value; drawQr(); pay.href = link(); amount.textContent = 'Pay ₹' + plans[plan].price_inr; } }, Object.entries(plans).map(([k, v]) => h('option', { value: k, selected: k === plan }, `${v.name} · ₹${v.price_inr}/month`)));
  const amount = h('b', null, 'Pay ₹' + plans[plan].price_inr); const pay = h('a', { class: 'btn', href: link() }, 'Open my UPI app');
  box.append(h('h3', null, 'Pay with UPI'), h('p', { class: 'muted' }, 'Scan with any UPI app (GPay, PhonePe, Paytm, FamPay...) or tap the button on your phone. Then paste the reference number shown after payment.'), sel, amount, qrBox, pay,
    h('p', { class: 'small muted' }, 'Or pay to: ' + info.vpa), utr,
    h('button', { class: 'btn primary', onclick: async (e) => { e.target.disabled = true; try { msg.textContent = await L.upiClaim(plan, utr.value.trim()); toast('Sent. We will unlock you soon.'); } catch (err) { toast(err.message, 7000); e.target.disabled = false; } } }, 'I have paid'), msg);
  drawQr(); return h('div', { class: 'card' }, box);
}
