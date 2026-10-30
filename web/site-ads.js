// Ads helper: remembers where a visitor came from (?utm_source=...&utm_campaign=...), and turns "Message us" into a
// copy-then-open box carrying a short ref code, so every enquiry says which ad it came from. Optional private-friendly counter.
(function () {
  var C = window.REELIO_CONFIG || {};
  var LSget = function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } };
  var LSset = function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} };
  var q = new URLSearchParams(location.search), ref = LSget('reelio.ref') || '';
  var src = q.get('utm_source') || q.get('src'), cmp = q.get('utm_campaign') || q.get('c');
  if (src || cmp) { ref = [src, cmp].filter(Boolean).join('-').replace(/[^\w-]/g, '').slice(0, 30); LSset('reelio.ref', ref); }
  // optional GoatCounter (no cookies). Put your code in app-config.js: goatcounter: 'yourname'
  if (C.goatcounter && /^[a-z0-9-]+$/i.test(C.goatcounter)) {
    var s = document.createElement('script'); s.async = true; s.src = 'https://gc.zgo.at/count.js';
    s.setAttribute('data-goatcounter', 'https://' + C.goatcounter + '.goatcounter.com/count'); document.head.appendChild(s);
  }
  var hi = function () { return document.documentElement.lang === 'hi'; };
  function openBox(href) {
    var d = document.createElement('dialog'); d.className = 'msg';
    var text = (hi() ? 'नमस्ते, मुझे Reelio चाहिए।' : 'Hi, I want to try Reelio.') + (ref ? ' (code: ' + ref + ')' : '');
    d.innerHTML = '<h3></h3><p></p><textarea readonly aria-label="Message"></textarea><div class="cta"></div>';
    d.querySelector('h3').textContent = hi() ? 'दो आसान कदम' : 'Two easy steps';
    d.querySelector('p').textContent = hi() ? '1. नीचे का संदेश कॉपी करें।  2. चैट खोलें और भेज दें।' : '1. Copy the message below.  2. Open the chat and paste it.';
    var ta = d.querySelector('textarea'); ta.value = text;
    var cta = d.querySelector('.cta');
    var copy = document.createElement('button'); copy.className = 'btn solid'; copy.textContent = hi() ? 'कॉपी करें' : 'Copy message';
    copy.onclick = function () { ta.select(); try { navigator.clipboard.writeText(text); } catch (e) { document.execCommand('copy'); } copy.textContent = hi() ? 'कॉपी हो गया' : 'Copied'; };
    var open = document.createElement('a'); open.className = 'btn'; open.href = href; open.target = '_blank'; open.rel = 'noopener'; open.textContent = hi() ? 'चैट खोलें' : 'Open chat';
    var close = document.createElement('button'); close.className = 'btn sm'; close.textContent = hi() ? 'बंद करें' : 'Close'; close.onclick = function () { d.close(); };
    cta.append(copy, open, close); document.body.appendChild(d); d.addEventListener('close', function () { d.remove(); }); d.showModal();
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-contact]');
    if (!a || !/^https?:/.test(a.href || '') || /^https:\/\/github\.com\//.test(a.href)) return;
    e.preventDefault(); openBox(a.href);
  });
})();
