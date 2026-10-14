"""Telegram alerts. Failing to notify must never break a run."""
from .util import http, env_base, iso, now, parse_iso, scrub

TG = lambda: env_base("TELEGRAM_BASE", "https://api.telegram.org")
ICON = {"posted": "✅", "failed": "⚠️", "limit": "⏳", "token": "🔑", "daily": "📊", "info": "ℹ️"}


class Notifier:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg
        n = (cfg.get("notify") or {}).get("telegram") or {}
        self.enabled = bool(n.get("enabled"))
        self.events = n.get("events") or {}
        self.sec = store.secret(n.get("conn", "telegram")) if self.enabled else {}   # may raise ValueError if locked
        self.state = store.status().get("notified", {})

    def send(self, kind, text, key=None, ttl_hours=0):
        """kind: posted|failed|limit|token|daily|info. `key`+`ttl_hours` stop the same alert repeating."""
        if not self.enabled or not self.events.get(kind, kind == "info"):
            return False
        if not (self.sec.get("bot_token") and self.sec.get("chat_id")):
            return False
        if key and ttl_hours:
            t = parse_iso(self.state.get(key))
            if t and (now() - t).total_seconds() < ttl_hours * 3600:
                return False
        try:
            r = http("POST", f"{TG()}/bot{self.sec['bot_token']}/sendMessage", retries=2, timeout=20,
                     data={"chat_id": self.sec["chat_id"], "text": f"{ICON.get(kind, '')} {text}"[:3900], "disable_web_page_preview": "true"})
            ok = r.status_code == 200
        except Exception:
            ok = False
        if ok and key:
            self.state[key] = iso()
        return ok
