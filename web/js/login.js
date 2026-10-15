import { t } from './i18n.js';
import { h, LS, toast, apiAuth } from './core.js';
import { logo, apiUrl } from './app.js';

/** Email + password sign in / sign up for the hosted version. Nothing about GitHub. */
export async function render(S, app) {
  let mode = 'login';
  const root = h('div', { class: 'paywall' });
  const draw = () => {
    const email = h('input', { type: 'email', autocomplete: 'email', placeholder: 'you@example.com', 'aria-label': 'Email' });
    const pw = h('input', { type: 'password', autocomplete: mode === 'login' ? 'current-password' : 'new-password', placeholder: mode === 'login' ? 'Password' : 'Choose a password (8+ characters)', 'aria-label': 'Password' });
    const go = async (e) => {
      e.preventDefault(); const b = e.submitter || root.querySelector('button.primary'); b.disabled = true;
      try { const r = await apiAuth(apiUrl(), mode === 'login' ? 'login' : 'signup', email.value, pw.value); LS.set('apitoken', r.token); S.token = r.token; S.data = null; S.cfg = null; location.hash = '#/home'; app.rerender(); }
      catch (er) { toast(er.message, 6000); b.disabled = false; }
    };
    root.replaceChildren(h('div', { class: 'wrap' }, logo('logo big'), h('h1', null, t(mode === 'login' ? 'Welcome back' : 'Create your account')), h('p', { class: 'muted' }, 'Your videos, posted automatically to Instagram and YouTube.'),
      h('form', { class: 'card col', style: 'max-width:380px;width:100%;text-align:left', onsubmit: go }, h('label', { class: 'f' }, t('Email'), email), h('label', { class: 'f' }, t('Password'), pw),
        h('button', { class: 'btn primary', type: 'submit' }, t(mode === 'login' ? 'Log in' : 'Sign up')),
        h('button', { class: 'btn', type: 'button', onclick: () => { mode = mode === 'login' ? 'signup' : 'login'; draw(); } }, t(mode === 'login' ? 'New here? Create an account' : 'I already have an account'))),
      h('p', { class: 'small muted' }, 'By continuing you agree to the ', h('a', { href: 'terms.html' }, 'Terms'), ' and ', h('a', { href: 'privacy.html' }, 'Privacy Policy'), '. Only post videos you own or have permission to use.')));
  };
  draw(); return root;
}
