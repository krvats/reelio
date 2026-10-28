// Reelio site script: film strip, day planner, screen tabs, language and theme. No libraries.
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); }, $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var C = window.REELIO_CONFIG || {};
  var LSget = function (k, d) { try { var v = localStorage.getItem('reelio.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  var LSset = function (k, v) { try { localStorage.setItem('reelio.' + k, JSON.stringify(v)); } catch (e) {} };

  // ---- where "Message us" goes: your own link from app-config.js, else a pre-filled GitHub issue on this repo
  (function () {
    var m = location.hostname.match(/^(.+)\.github\.io$/), repo = location.pathname.split('/')[1] || 'reelio', url = C.contactUrl || '';
    if (!url && m) url = 'https://github.com/' + m[1] + '/' + repo + '/issues/new?title=' + encodeURIComponent('Reelio access request') + '&body=' + encodeURIComponent('I run ___ Instagram pages and ___ YouTube channels.');
    if (url) $$('[data-contact]').forEach(function (a) { a.href = url; if (/^https?:/.test(url)) { a.target = '_blank'; a.rel = 'noopener'; } });
  })();

  // ---- film strip: today's posts being checked off, one grease-pencil circle on the next frame
  var track = $('#track'), TOTAL = 44, PER_DAY = 24, FW = 66;
  var now = new Date(), done = Math.min(PER_DAY - 1, now.getHours() + (now.getMinutes() > 12 ? 1 : 0));
  var circle = '<svg viewBox="0 0 80 106" aria-hidden="true"><path d="M14 26C22 8 52 4 68 18c14 13 10 52-6 70C48 102 18 100 10 78 4 62 8 40 18 30"/></svg>';
  var frames = [];
  for (var i = 0; i < TOTAL; i++) { var f = document.createElement('div'); f.className = 'fr' + (i < done ? ' done' : ''); track.appendChild(f); frames.push(f); }
  function fmt12(mins) { var d = new Date(); d.setHours(0, mins, 0, 0); return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
  function slotMins(i) { return ((i % PER_DAY) * 60 + 14 + ((i * 17) % 31)); }
  function place(animate) {
    var vw = document.documentElement.clientWidth, shift = Math.min(24, vw * 0.3 - (done * FW + 28));
    if (!animate) track.style.transition = 'none';
    track.style.transform = 'translateX(' + shift + 'px)';
    if (!animate) { track.offsetWidth; track.style.transition = ''; }
  }
  function mark() {
    frames.forEach(function (f, j) { f.classList.toggle('done', j < done); var has = f.classList.contains('next'); if (j === done && !has) { f.classList.add('next'); f.insertAdjacentHTML('beforeend', circle); } else if (j !== done && has) { f.classList.remove('next'); var sv = f.querySelector('svg'); if (sv) sv.remove(); } });
    $('#st_done').textContent = done + ' of ' + PER_DAY;
    $('#st_next').textContent = nextText(fmt12(slotMins(done)));
  }
  var nextText = function (t) { return (LANG === 'hi' ? 'अगली पोस्ट ' : 'Next post at ') + t + '.'; };
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  place(false); mark();
  window.addEventListener('resize', function () { place(false); });
  // once on screen, the strip advances a few frames, as the real thing does through the day
  var ticks = 0, timer = null;
  function tick() { if (document.hidden || ticks >= 5 || done >= PER_DAY - 1) return; done++; ticks++; place(true); mark(); }
  if (!reduce && 'IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting && !timer) timer = setInterval(tick, 3400); else if (!e.isIntersecting && timer) { clearInterval(timer); timer = null; } }); }, { threshold: 0.3 }).observe($('.strip'));
  }

  // ---- day planner
  var ppd = $('#ppd'), times = $('#times');
  function plan() {
    var n = +ppd.value, start = 540, span = 780, gap = span / n, out = [];
    for (var j = 0; j < n; j++) { var jit = (((j * 53 + n * 29) % 41) / 41 - 0.5) * gap * 0.4; out.push(Math.round(start + (j + 0.5) * gap + jit)); }
    $('#ppdv').textContent = n;
    times.innerHTML = out.map(function (m) { return '<span>' + fmt12(m) + '</span>'; }).join('');
  }
  ppd.addEventListener('input', plan); plan();

  // ---- screenshots
  var tabs = $$('#shottabs button'), dimg = $('#shotd'), mimg = $('#shotm');
  var ALT = { home: 'Home', pages: 'Pages and channels', flows: 'Flows', schedule: 'Schedule', stats: 'Stats' };
  tabs.forEach(function (b) { b.addEventListener('click', function () {
    var k = b.getAttribute('data-shot'); tabs.forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
    dimg.src = 'shots/' + k + '-d.webp'; mimg.src = 'shots/' + k + '-m.webp'; dimg.alt = 'Reelio ' + ALT[k] + ' screen on a computer'; mimg.alt = 'Reelio ' + ALT[k] + ' screen on a phone';
  }); });

  // ---- theme
  var themeBtn = $('#theme');
  function dark() { var t = document.documentElement.dataset.theme; return t ? t === 'dark' : (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches); }
  function themeLabel() { themeBtn.textContent = dark() ? (LANG === 'hi' ? 'लाइट' : 'Light') : (LANG === 'hi' ? 'डार्क' : 'Dark'); }
  themeBtn.addEventListener('click', function () { var t = dark() ? 'light' : 'dark'; document.documentElement.dataset.theme = t; LSset('theme', t); themeLabel(); });

  // ---- language (English and Hindi). English text stays in the HTML; Hindi is swapped in.
  var HI = {
    nav_features: 'खूबियाँ', nav_how: 'कैसे चलता है', nav_demo: 'डेमो', nav_faq: 'सवाल', get_access: 'एक्सेस पाएँ',
    h1: 'आपके वीडियो खुद पोस्ट होते हैं।',
    lede: 'Reelio आपके अपने वीडियो आपकी चुनी हुई टाइमिंग पर इंस्टाग्राम रील्स और यूट्यूब शॉर्ट्स पर डालता है, जितने चाहें उतने पेज और चैनल के लिए। आपका फ़ोन और लैपटॉप बंद हो तब भी चलता रहता है।',
    try_demo: 'लाइव डेमो देखें', today_label: 'आज एक पेज पर:', posted_word: 'पोस्ट हुए।',
    works1: 'इंस्टाग्राम रील्स और यूट्यूब शॉर्ट्स पर पोस्ट करता है।', works2: 'गूगल ड्राइव, यूट्यूब, इंस्टाग्राम या आपके अपलोड से वीडियो लेता है।', works3: 'कुछ गड़बड़ हो तो टेलीग्राम पर बताता है।',
    why_h: 'तीन पेज के बाद हाथ से पोस्ट करना मुश्किल हो जाता है।', by_hand: 'हाथ से', with_r: 'Reelio के साथ',
    bh1: 'हर ऐप खोलो, अपलोड करो, कैप्शन लिखो, हैशटैग लगाओ।', bh2: 'हर पेज के लिए, हर दिन, यही दोबारा।', bh3: 'व्यस्त हुए तो एक दिन छूट गया।', bh4: 'एक ही वीडियो दो बार पोस्ट हो गया और पता भी नहीं चला।',
    wr1: 'वीडियो गूगल ड्राइव फ़ोल्डर में डालें, या किसी यूट्यूब चैनल को चुनें।', wr2: 'बताएँ रोज़ कितने और कब।', wr3: 'Reelio सही कैप्शन के साथ समय पर पोस्ट करता है।', wr4: 'हर पोस्ट दर्ज होती है, इसलिए कुछ भी दो बार नहीं जाता।',
    how_h: 'एक बार सेट करें। जब मन हो तब देखें।', s1h: 'अपने पेज जोड़ें', s1p: 'इंस्टाग्राम, यूट्यूब और गूगल ड्राइव जोड़ें। आपके लॉगिन ऐसे पासफ़्रेज़ से बंद रहते हैं जो सिर्फ़ आप जानते हैं।',
    s2h: 'एक फ़्लो बनाएँ', s2p: 'फ़्लो वीडियो को उसकी जगह से उस जगह ले जाता है जहाँ आप पोस्ट करते हैं। रोज़ की पोस्ट, समय, कैप्शन और लुक चुनें।',
    s3h: 'बस चलने दें', s3p: 'Reelio हर पाँच मिनट में देखता है और जो पोस्ट होनी है उसे डाल देता है। कुछ आपकी ज़रूरत हो तो बताता है क्या करना है, और टेलीग्राम पर मैसेज भी भेज सकता है।',
    feat_h: 'कई पेज चलाने वालों के लिए बना।', feat_sub: 'वो सब जो आप हाथ से करते, और वो भी जो आप भूल जाते।',
    f1h: 'कई पेज, एक स्क्रीन', f1p: 'हर इंस्टाग्राम पेज और यूट्यूब चैनल आज की प्रगति के साथ देखें। कई चुनकर सबको एक साथ रोकें, चालू करें या रोज़ की पोस्ट बदलें।',
    f2h: 'कहीं से भी, कहीं भी', f2p: 'वीडियो गूगल ड्राइव, यूट्यूब चैनल या चुने हुए वीडियो, इंस्टाग्राम पेज या आपके अपलोड से आ सकते हैं। वे इंस्टाग्राम रील्स या यूट्यूब शॉर्ट्स पर जा सकते हैं।',
    f3h: 'हर पोस्ट पर कंट्रोल', f3p: 'रोज़ 100 तक पोस्ट, समय की खिड़की, हफ़्ते के दिन, छुट्टी के दिन, और थोड़ा बदलाव ताकि पोस्टिंग स्वाभाविक लगे। किसी भी वीडियो को आगे करें, कैप्शन बदलें, छोड़ें या अभी पोस्ट करें।',
    f4h: 'कैप्शन और लुक', f4p: 'तय, रैंडम या टेबल वाले कैप्शन, हैशटैग सेट और वेरिएंट। फ़िल्टर, वर्टिकल में फ़िट करने के लिए ब्लर या क्रॉप, वॉटरमार्क और कवर फ़्रेम।',
    f5h: 'न दोबारा, न गायब', f5p: 'हर पोस्ट का पक्का रिकॉर्ड डुप्लिकेट रोकता है, फ़ाइल का नाम बदल जाए तब भी। एक खराब वीडियो बाकी कतार को नहीं रोकता।',
    f6h: 'लंबे वीडियो, अपने-आप कटे हुए', f6p: 'घंटे भर का वीडियो या लाइव स्ट्रीम शॉर्ट्स जितने टुकड़ों में बदलें और कतार में लगाएँ।',
    f7h: 'खुद चलता रहता है', f7p: 'क्लाउड का शेड्यूल कभी देर कर देता है। Reelio पहचानकर खुद चेक शुरू कर देता है। यूट्यूब डाउनलोड रोके तो आपकी सेव की हुई कुकीज़ बारी-बारी आज़माता है।',
    f8h: 'आसान भाषा में मदद', f8p: 'कुछ फेल हो तो Reelio बताता है क्यों और क्या दबाना है। एक बटन से जाँच हो जाती है कि सब अकाउंट जुड़े हैं।',
    f9h: 'काम के आँकड़े', f9p: 'हर इंस्टाग्राम पेज के व्यूज़, लाइक और पोस्ट करने के सबसे अच्छे घंटे।',
    f10h: 'डिज़ाइन से ही सुरक्षित', f10p: 'लॉगिन आपके ब्राउज़र में AES-256 से एन्क्रिप्ट होकर ही सेव होते हैं। सिर्फ़ इंस्टाग्राम और यूट्यूब के आधिकारिक कनेक्शन इस्तेमाल होते हैं।',
    f11h: 'फ़ोन के लिए बना', f11p: 'ऐप की तरह इंस्टॉल करें। बड़े बटन, लाइट और डार्क, अक्षर का आकार बदलना, और मुख्य स्क्रीन हिंदी में।',
    pl_h: 'एक दिन का प्लान देखें', pl_label: 'रोज़ की पोस्ट', pl_note: 'समय हर दिन कुछ मिनट बदलता है, ताकि पोस्टिंग रोबोट जैसी न लगे। यह सुबह 9 से रात 10 के बीच का नमूना है।',
    demo_h: 'असली ऐप खुद चलाकर देखें।', demo_sub: 'डेमो में असली Reelio स्क्रीन काल्पनिक पेजों के साथ चलती हैं। कुछ सेव नहीं होता और कुछ पोस्ट नहीं होता।',
    t_home: 'होम', t_pages: 'पेज', t_flows: 'फ़्लो', t_schedule: 'शेड्यूल', t_stats: 'आँकड़े', open_demo: 'लाइव डेमो खोलें',
    lim_h: 'क्या उम्मीद रखें।', lim1: 'इंस्टाग्राम आधिकारिक कनेक्शन से हर अकाउंट पर रोज़ 100 पोस्ट तक देता है। नए यूट्यूब प्रोजेक्ट रोज़ करीब छह वीडियो अपलोड कर सकते हैं।',
    lim2: 'पोस्टिंग GitHub के शेड्यूल पर चलती है, लगभग हर पाँच मिनट में। देर हो सकती है; Reelio उसी दिन भरपाई कर लेता है।', lim3: 'सिर्फ़ वही वीडियो पोस्ट करें जो आपके हैं या जिनकी अनुमति है।',
    acc_h: 'Reelio पाएँ।', acc_sub: 'Reelio आपके साथ बैठकर सेट होता है, इसलिए बताइए आप क्या चलाते हैं।',
    a1: 'हमें मैसेज करें कि आप कितने इंस्टाग्राम पेज और यूट्यूब चैनल चलाते हैं।', a2: 'हम बताएँगे क्या फ़िट होता है और आपका एक्सेस भेजेंगे।', a3: 'Reelio खोलें और अपने अकाउंट जोड़ें। ऐप हर कदम पर साथ चलता है; करीब 15 मिनट लगते हैं।',
    card_h: 'जब आप तैयार हों', card_p: 'प्लान और भुगतान मैसेज में तय होते हैं। इस साइट पर कुछ चार्ज नहीं होता।', msg_us: 'इंस्टाग्राम पर मैसेज करें', have_access: 'मेरे पास एक्सेस है', card_small: 'पहले देखना है? लाइव डेमो के लिए साइन-अप नहीं चाहिए।',
    faq_h: 'सवाल।', q1: 'क्या फ़ोन या कंप्यूटर चालू रखना होगा?', a_1: 'नहीं। Reelio क्लाउड पर चलता है और अपने-आप पोस्ट करता है।',
    q2: 'कौन से अकाउंट चलते हैं?', a_2: 'इंस्टाग्राम प्रोफ़ेशनल अकाउंट (क्रिएटर या बिज़नेस) और यूट्यूब चैनल, उनके आधिकारिक कनेक्शन से।',
    q3: 'क्या इंस्टाग्राम और यूट्यूब इसकी अनुमति देते हैं?', a_3: 'Reelio सिर्फ़ उनके आधिकारिक पब्लिशिंग कनेक्शन इस्तेमाल करता है। यह अकाउंट स्क्रैप नहीं करता और अनौपचारिक लॉगिन नहीं लेता। सिर्फ़ अपने या अनुमति वाले वीडियो पोस्ट करना आपकी ज़िम्मेदारी है।',
    q4: 'मेरे लॉगिन कहाँ रखे जाते हैं?', a_4: 'सेव होने से पहले उन्हें ऐसे पासफ़्रेज़ से एन्क्रिप्ट किया जाता है जो सिर्फ़ आप जानते हैं, और ऐप में वे दोबारा नहीं दिखाए जाते।',
    q5: 'रोज़ कितनी पोस्ट शेड्यूल कर सकता हूँ?', a_5: 'आप चुनते हैं, इंस्टाग्राम की सीमा तक: हर अकाउंट पर रोज़ 100। यूट्यूब पर यूट्यूब का अपना कोटा लागू होता है।',
    q6: 'अगर यूट्यूब डाउनलोड रोक दे तो?', a_6: 'Reelio आपकी सेव कुकीज़ बारी-बारी आज़माता है, जो फेल हों उन्हें आराम देता है, और फिर बैकअप ड्राइव फ़ोल्डर पर जाता है। सब फेल हो तो साफ़ बताता है क्या जोड़ना है।',
    q7: 'क्या पहले आज़मा सकता हूँ?', a_7: 'हाँ। लाइव डेमो में साइन-अप नहीं चाहिए और यह नमूना डेटा इस्तेमाल करता है।',
    f_terms: 'शर्तें', f_priv: 'प्राइवेसी', f_dmca: 'कॉपीराइट', open_app: 'ऐप खोलें'
  };
  var LANG = LSget('lang', /^hi/i.test(navigator.language || '') ? 'hi' : 'en');
  var langBtn = $('#lang');
  function applyLang() {
    $$('[data-i]').forEach(function (el) { var k = el.getAttribute('data-i'); if (el.dataset.en == null) el.dataset.en = el.textContent; el.textContent = (LANG === 'hi' && HI[k]) ? HI[k] : el.dataset.en; });
    document.documentElement.lang = LANG; langBtn.textContent = LANG === 'hi' ? 'English' : 'हिन्दी'; themeLabel();
    $('#st_next').textContent = nextText(fmt12(slotMins(done)));
  }
  langBtn.addEventListener('click', function () { LANG = LANG === 'hi' ? 'en' : 'hi'; LSset('lang', LANG); applyLang(); });
  applyLang();
})();
