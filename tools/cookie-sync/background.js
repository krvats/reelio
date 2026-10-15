import { syncNow } from './sync.js';

const NAME = 'reelio-cookie-sync';
function ensureAlarm() { chrome.alarms.get(NAME, (a) => { if (!a) chrome.alarms.create(NAME, { delayInMinutes: 1, periodInMinutes: 60 }); }); }
chrome.runtime.onInstalled.addListener(ensureAlarm);
chrome.runtime.onStartup.addListener(() => { ensureAlarm(); syncNow().catch(() => {}); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === NAME) syncNow().catch(() => {}); });
ensureAlarm();
