// Tiny translation layer. t('English text') returns the Hindi version when the language is Hindi. Missing words fall back to English, so nothing breaks.
import { LS } from './core.js';
const HI = {
  'Home': 'होम', 'Pages': 'पेज', 'Flows': 'फ्लो', 'Videos': 'वीडियो', 'More': 'और', 'Accounts': 'अकाउंट', 'Schedule': 'समय-सारणी', 'Stats': 'आँकड़े', 'Activity': 'गतिविधि', 'Settings': 'सेटिंग्स', 'Help': 'मदद',
  'Pause everything': 'सब कुछ रोकें', 'Turn posting on': 'पोस्टिंग चालू करें', 'Check now': 'अभी जाँचें', 'All good.': 'सब ठीक है।', 'Ready and waiting.': 'तैयार है, इंतज़ार में।', 'Posting is paused.': 'पोस्टिंग रुकी हुई है।',
  'posted today': 'आज पोस्ट हुए', 'waiting in line': 'कतार में', 'need a look': 'देखने की ज़रूरत', 'recent success': 'हाल की सफलता', 'What is happening': 'क्या हो रहा है',
  'Getting started': 'शुरुआत करें', 'Connect an Instagram page or YouTube channel': 'इंस्टाग्राम पेज या यूट्यूब चैनल जोड़ें', 'Create a flow (where videos come from and go to)': 'एक फ्लो बनाएँ (वीडियो कहाँ से आएँ और कहाँ जाएँ)', 'Let Reelio check once': 'Reelio को एक बार जाँचने दें', 'Get your first post': 'अपनी पहली पोस्ट पाएँ',
  'Pages & channels': 'पेज और चैनल', 'Add': 'जोड़ें', 'New flow': 'नया फ्लो', 'Edit': 'बदलें', 'See videos': 'वीडियो देखें', 'Run now': 'अभी चलाएँ', 'Save': 'सेव करें', 'Cancel': 'रद्द करें',
  'Welcome back': 'वापसी पर स्वागत है', 'Create your account': 'अपना अकाउंट बनाएँ', 'Log in': 'लॉग इन', 'Sign up': 'साइन अप', 'Email': 'ईमेल', 'Password': 'पासवर्ड', 'New here? Create an account': 'नए हैं? अकाउंट बनाएँ', 'I already have an account': 'मेरा अकाउंट पहले से है',
  'Pick a plan to start': 'शुरू करने के लिए प्लान चुनें', 'Most popular': 'सबसे लोकप्रिय', 'Subscription': 'सब्सक्रिप्शन', 'Manage billing': 'बिलिंग संभालें', 'Add another device': 'दूसरा डिवाइस जोड़ें',
  'How it looks': 'दिखावट', 'Text size': 'अक्षर का आकार', 'Language': 'भाषा', 'Time zone': 'समय क्षेत्र', 'Backup': 'बैकअप', 'Sign out of this device': 'इस डिवाइस से साइन आउट',
  'Which days?': 'कौन से दिन?', 'Days off (optional)': 'छुट्टी के दिन (वैकल्पिक)', 'First comment': 'पहला कमेंट', 'Posts per day': 'रोज़ कितनी पोस्ट', 'Done': 'हो गया', 'To do': 'करना है',
};
export const lang = () => LS.get('lang', (navigator.language || '').startsWith('hi') ? 'hi' : 'en');
export const t = (s) => (lang() === 'hi' && HI[s]) || s;
export const setLang = (l) => { LS.set('lang', l); document.documentElement.lang = l; };
document.documentElement.lang = lang();
