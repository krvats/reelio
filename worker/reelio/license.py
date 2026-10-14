"""Offline license check. The app hands the worker a signed entitlement (Ed25519) through the private data repo; the worker verifies it
with the public key, so no network call or secret is needed. Turned on only when a public key is configured, so personal installs run open.

Token claims used: st (state), plan, lim{accounts,posts_month}, exp (24 h), wv (worker-valid-until: lets 24/7 posting continue while the owner
is not opening the app, bounded by the paid period + grace). Honest limit: code on a user's own repo can be patched; see CONTEXT.md."""
import base64, json, os
from .util import read_json, now


def _unb64u(s):
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def verify_token(pub_x, token, at):
    """Return claims, or raise ValueError with a plain-language reason."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        h, b, s = str(token).split(".")
        Ed25519PublicKey.from_public_bytes(_unb64u(pub_x)).verify(_unb64u(s), f"{h}.{b}".encode())
        return json.loads(_unb64u(b))
    except (InvalidSignature, ValueError, TypeError):
        raise ValueError("The saved plan is not valid. Open the Reelio app once to refresh it.")


def pubkey(cfg):
    return os.environ.get("REELIO_LICENSE_PUBKEY") or (cfg or {}).get("license_pubkey") or ""


def check(store, cfg, at=None):
    """-> {enforced, active, plan, accounts, posts_month, message}. Never raises."""
    px = pubkey(cfg)
    if not px:
        return {"enforced": False, "active": True, "plan": "open", "accounts": 10 ** 6, "posts_month": 10 ** 9, "message": ""}
    at = (at or now()).timestamp()
    off = {"enforced": True, "active": False, "plan": None, "accounts": 0, "posts_month": 0}
    lic = read_json(store.p("license.json"), None) or {}
    if not lic.get("token"):
        return {**off, "message": "No active plan. Open the Reelio app and pick a plan; posting continues by itself afterwards."}
    try:
        c = verify_token(px, lic["token"], at)
    except ValueError as e:
        return {**off, "message": str(e)}
    valid_until = max(c.get("exp", 0), c.get("wv", 0))
    if valid_until < at:
        return {**off, "message": "Your plan needs renewing. Open the Reelio app so it can refresh, or check your payment."}
    lim = c.get("lim") or {}
    return {"enforced": True, "active": True, "plan": c.get("plan"), "state": c.get("st"), "accounts": int(lim.get("accounts", 1)),
            "posts_month": int(lim.get("posts_month", 0)), "message": ""}


def allowed_accounts(cfg, limit):
    """Targets (accounts/channels) that may post under this plan: first N in the order they were added."""
    seen = []
    for r in cfg.get("routes", []):
        if r.get("enabled", True):
            k = r["target"]["conn"]
            if k not in seen:
                seen.append(k)
    return set(seen[:max(0, limit)])


def month_posts(store, at=None):
    t = (at or now())
    pref = t.strftime("%Y-%m")
    return sum(1 for e in store.ledger()["entries"] if str(e.get("at", "")).startswith(pref) and e.get("status") in ("posted", "unknown_id"))
