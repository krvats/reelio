#!/usr/bin/env python3
"""Project memory for Reelio. The project carries its own context so ANY new chat can continue from just the zip.

  python tools/handoff.py snapshot [--note "what I just did"] [--tests]   save a fingerprint of every file + a worklog line
  python tools/handoff.py diff                                           show what changed since the last snapshot (YOUR edits too)
  python tools/handoff.py prompt                                         write NEXT_CHAT_PROMPT.md automatically (no AI needed)
  python tools/handoff.py check                                          exit 1 if the snapshot is out of date
"""
import os, sys, json, hashlib, datetime, subprocess, re, argparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAN = os.path.join(ROOT, "docs", "MANIFEST.json")
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".wrangler", "screens"}
SKIP_FILES = {"NEXT_CHAT_PROMPT.md", "MANIFEST.json", "WORKLOG.md", "TESTS.json", ".DS_Store"}
CODE_EXT = (".py", ".js", ".mjs", ".css", ".html", ".md", ".yml", ".json", ".toml", ".svg", ".webmanifest", ".txt")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def tree():
    out = {}
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for f in fns:
            if f in SKIP_FILES or not f.endswith(CODE_EXT):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            data = open(p, "rb").read()
            out[rel] = {"sha": hashlib.sha256(data).hexdigest()[:16], "lines": data.count(b"\n") + 1, "bytes": len(data)}
    return dict(sorted(out.items()))


def load():
    try:
        return json.load(open(MAN, encoding="utf-8"))
    except Exception:
        return None


def version():
    try:
        return open(os.path.join(ROOT, "VERSION")).read().strip()
    except Exception:
        return "0"


def compare(old, new):
    o, n = (old or {}).get("files", {}), new
    return {"added": sorted(set(n) - set(o)), "removed": sorted(set(o) - set(n)), "changed": sorted(k for k in n if k in o and o[k]["sha"] != n[k]["sha"])}


def run_tests():
    res = {}
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=os.path.join(ROOT, "worker"), capture_output=True, text=True, timeout=900)
        m = re.search(r"Ran (\d+) tests", p.stderr); res["python"] = {"ran": int(m[1]) if m else 0, "ok": p.returncode == 0}
    except Exception as e:
        res["python"] = {"ran": 0, "ok": False, "error": str(e)[:100]}
    lic = os.path.join(ROOT, "license")
    if os.path.isdir(os.path.join(lic, "test")):
        try:
            p = subprocess.run(["node", "--test", "test/license.test.mjs"], cwd=lic, capture_output=True, text=True, timeout=300)
            m = re.search(r"# pass (\d+)", p.stdout); f = re.search(r"# fail (\d+)", p.stdout)
            res["license"] = {"ran": int(m[1]) + int(f[1]) if m and f else 0, "ok": p.returncode == 0}
        except Exception as e:
            res["license"] = {"ran": 0, "ok": False, "error": str(e)[:100]}
    res["at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(res, open(os.path.join(ROOT, "docs", "TESTS.json"), "w"), indent=1)
    return res


def cmd_snapshot(a):
    old = load(); files = tree(); d = compare(old, files)
    if a.tests:
        run_tests()
    man = {"version": version(), "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": files}
    os.makedirs(os.path.dirname(MAN), exist_ok=True)
    json.dump(man, open(MAN, "w", encoding="utf-8"), indent=1)
    note = a.note or "snapshot"
    with open(os.path.join(ROOT, "docs", "WORKLOG.md"), "a", encoding="utf-8") as f:
        f.write(f"- {man['at']} v{man['version']}: {note} (+{len(d['added'])} added, ~{len(d['changed'])} changed, -{len(d['removed'])} removed)\n")
    print(f"snapshot saved: {len(files)} files, v{man['version']}. added {len(d['added'])}, changed {len(d['changed'])}, removed {len(d['removed'])}")


def cmd_diff(a):
    old = load()
    if not old:
        print("No snapshot yet."); return 0
    d = compare(old, tree())
    print(f"Changes since the snapshot taken {old['at']} (v{old['version']}):")
    for k in ("added", "changed", "removed"):
        for f in d[k]:
            print(f"  {k:8} {f}")
    if not any(d.values()):
        print("  nothing: the files are exactly as last saved.")
    return 0


def cmd_check(a):
    old = load(); d = compare(old, tree())
    if any(d.values()):
        print("snapshot is stale:", {k: len(v) for k, v in d.items()}); return 1
    print("snapshot is current"); return 0


def read(p, default=""):
    try:
        return open(os.path.join(ROOT, p), encoding="utf-8").read()
    except Exception:
        return default


def cmd_prompt(a):
    old = load(); files = tree(); d = compare(old, files)
    tests = {}
    try: tests = json.load(open(os.path.join(ROOT, "docs", "TESTS.json")))
    except Exception: pass
    road = read("docs/ROADMAP.md")
    openitems = [l for l in road.splitlines() if l.strip().startswith("- [ ]")]
    work = read("docs/WORKLOG.md").strip().splitlines()[-25:]
    shots = sorted(os.listdir(os.path.join(ROOT, "docs", "screens"))) if os.path.isdir(os.path.join(ROOT, "docs", "screens")) else []
    groups = {}
    for f, m in files.items():
        groups.setdefault(f.split("/")[0] if "/" in f else ".", []).append(f"{f} ({m['lines']})")
    t = []
    t.append("# Continue the Reelio project (auto-generated handoff, no summary needed from me)\n")
    t.append("I attached the project zip. It carries its own memory. Do exactly this, in order, then keep working without asking me to re-explain:\n")
    t.append("1. Unzip it. Read `CLAUDE.md` (rules), `CONTEXT.md` (what the product is, architecture, decisions), `docs/ROADMAP.md` (what is done and what is next), and the end of `docs/WORKLOG.md`.")
    t.append("2. Run `python tools/handoff.py diff`. Anything listed there was changed after the last saved snapshot. That is either my own edit or unfinished work from the previous chat. Read those files first and treat my edits as intentional.")
    t.append("3. Look at the images in `docs/screens/` to see the current UI.")
    t.append("4. Run the tests (`cd worker && python -m unittest discover -s tests`, and `cd license && node --test test/*.test.mjs`). Report the result in one line.")
    t.append("5. Continue with the first unchecked item in `docs/ROADMAP.md`. Before you finish each work block run `python tools/handoff.py snapshot --note \"...\"` and update CONTEXT.md/ROADMAP.md/CHANGELOG so the next chat can continue again. Deliver a new zip each time.")
    t.append("\nIf I add a message below this line, that message wins over the roadmap order.\n")
    t.append("---\n## State captured by `tools/handoff.py prompt`")
    t.append(f"- Version: {version()} · last snapshot: {old['at'] if old else 'none'}")
    if tests:
        t.append("- Last recorded tests: " + ", ".join(f"{k}: {v['ran']} ran, {'passing' if v['ok'] else 'FAILING'}" for k, v in tests.items() if isinstance(v, dict)) + f" (at {tests.get('at', '?')})")
    if any(d.values()):
        t.append("- Changed since last snapshot: " + "; ".join(f"{k}: {', '.join(v[:12])}{' ...' if len(v) > 12 else ''}" for k, v in d.items() if v))
    else:
        t.append("- No changes since the last snapshot.")
    t.append(f"- Screenshots available: {', '.join(shots) if shots else 'none'}")
    t.append("\n### Open roadmap items")
    t.extend(openitems[:25] or ["- (none listed)"])
    t.append("\n### Recent worklog")
    t.extend(work or ["- (empty)"])
    t.append("\n### File map")
    for g, fl in groups.items():
        t.append(f"- {g}/: " + ", ".join(fl[:14]) + (f" ... (+{len(fl) - 14} more)" if len(fl) > 14 else ""))
    open(os.path.join(ROOT, "NEXT_CHAT_PROMPT.md"), "w", encoding="utf-8").write("\n".join(t) + "\n")
    print("wrote NEXT_CHAT_PROMPT.md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="c", required=True)
    s = sp.add_parser("snapshot"); s.add_argument("--note"); s.add_argument("--tests", action="store_true")
    for n in ("diff", "prompt", "check"): sp.add_parser(n)
    a = ap.parse_args()
    sys.exit({"snapshot": cmd_snapshot, "diff": cmd_diff, "prompt": cmd_prompt, "check": cmd_check}[a.c](a) or 0)
