#!/usr/bin/env python3
"""Browser smoke check (demo mode, no accounts): every screen on phone and desktop, light and dark; no console errors,
no sideways scrolling; Save to Drive form rules; share link; landing page; ads page. usage: python tools/ui_check.py"""
import os, sys, threading, functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEB = os.path.join(ROOT, "web"); PORT = 8794
ROUTES = ["home", "pages", "flows", "queue", "accounts", "schedule", "analytics", "grab", "more", "settings", "help", "logs"]


class Q(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(Q, directory=WEB))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright
    fails, errors = [], []
    B = f"http://127.0.0.1:{PORT}/"
    with sync_playwright() as p:
        b = p.chromium.launch()
        for dev, vp in (("mobile", {"width": 390, "height": 844}), ("desktop", {"width": 1280, "height": 820})):
            for scheme in ("light", "dark"):
                ctx = b.new_context(viewport=vp, color_scheme=scheme, service_workers="block"); pg = ctx.new_page()
                pg.on("pageerror", lambda e: errors.append(str(e))); pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.goto(B + "app.html?demo=1#/home"); pg.wait_for_selector("#app", timeout=20000)
                for r in ROUTES:
                    pg.evaluate(f"location.hash='#/{r}'"); pg.wait_for_timeout(450)
                    over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    if over > 2: fails.append(f"{dev}/{scheme}/{r}: sideways scroll {over}px")
                    if not pg.inner_text("main").strip(): fails.append(f"{dev}/{scheme}/{r}: empty")
                ctx.close()
        # Save to Drive rules + demo worker + share link
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, service_workers="block"); pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e))); pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(B + "app.html?demo=1&url=https%3A%2F%2Fyoutu.be%2FABCDEFGHIJK%3Fsi%3Dzz#/home"); pg.wait_for_timeout(1500)
        if "#/grab" not in pg.url: fails.append("share link did not open Save to Drive")
        pg.wait_for_selector("textarea[aria-label=Links]", timeout=8000)
        if "youtu.be/ABCDEFGHIJK" not in pg.input_value("textarea[aria-label=Links]"): fails.append("shared link not filled in")
        pg.click("button:has-text('Save to Drive')"); pg.wait_for_timeout(400)
        if "Tick the box" not in pg.inner_text("body"): fails.append("no warning without the ownership tick")
        pg.wait_for_timeout(3500); pg.check("#gr_confirm"); pg.click("button:has-text('Save to Drive')")
        pg.wait_for_selector("text=Adding 1 link", timeout=5000)
        pg.wait_for_selector("text=Sample video", timeout=15000)
        for need in ("Check for new videos",):
            pass
        ctx.close()
        # landing + ads page
        for dev, vp in (("mobile", {"width": 390, "height": 844}), ("desktop", {"width": 1280, "height": 820})):
            for scheme in ("light", "dark"):
                ctx = b.new_context(viewport=vp, color_scheme=scheme); pg = ctx.new_page()
                pg.on("pageerror", lambda e: errors.append(str(e))); pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.goto(B + "index.html?utm_source=instagram&utm_campaign=test"); pg.wait_for_timeout(900)
                over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 2: fails.append(f"landing {dev}/{scheme}: sideways scroll {over}px")
                if dev == "desktop" and scheme == "light":
                    pg.screenshot(path=os.path.join(ROOT, "docs", "screens", "landing-desktop.png"))
                    pg.click("[data-contact]"); pg.wait_for_timeout(300)
                    t = pg.input_value("dialog.msg textarea") if pg.query_selector("dialog.msg textarea") else ""
                    if "instagram-test" not in t: fails.append("message box lacks the ref code: " + t)
                pg.goto(B + "promote.html"); pg.wait_for_timeout(500)
                if "utm_source=instagram" not in pg.input_value("#link"): fails.append("promote: link has no utm")
                ctx.close()
        b.close()
    errors = [e for e in errors if "Failed to load resource" not in e and "favicon" not in e and "cdnjs" not in e and "gc.zgo" not in e and "ERR_" not in e]
    if errors: fails.append("browser errors: " + "; ".join(sorted(set(errors))[:5]))
    print("UI CHECK:", "OK" if not fails else "FAILED")
    for f in fails: print(" -", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
