"""Saving files INTO Google Drive (the other direction from sources/drive.py, which only reads).

Uses the `drive.file` permission: Reelio can only see and change files and folders that Reelio itself made.
That is why the main folder is created by Reelio (and can then be renamed or moved anywhere by you; Reelio
keeps its access because it remembers the folder's ID, not its place).

Every uploaded file carries a hidden tag (appProperties.srcId = where it came from). Before uploading we look
for that tag in the target folder, so a run that was killed mid-upload never makes a duplicate.
"""
import os, re, json, datetime
from .util import http, env_base, now, sleep, HttpFail
from .errors import AccountProblem, ItemProblem

API = lambda: env_base("DRIVE_API", "https://www.googleapis.com/drive/v3")
UPLOAD = lambda: env_base("DRIVE_UPLOAD", "https://www.googleapis.com/upload/drive/v3")
FOLDER = "application/vnd.google-apps.folder"
GRAIN = 256 * 1024          # Drive wants chunks in multiples of 256 KiB (except the last one)


def _j(r):
    try:
        return r.json()
    except Exception:
        return {}


def drive_error(status, body):
    """Google's Drive error -> a plain-language Problem."""
    e = (body or {}).get("error", {}) if isinstance(body, dict) else {}
    msg = str(e.get("message", "")) if isinstance(e, dict) else str(e)
    reason = ""
    try:
        reason = (e.get("errors") or [{}])[0].get("reason", "") or e.get("status", "")
    except Exception:
        pass
    low = msg.lower()
    if reason == "storageQuotaExceeded" or "storage quota" in low:
        return AccountProblem("Your Google Drive is full.", "Free some space (or add storage) and Reelio carries on by itself.", reason, 360, "quota")
    if reason in ("rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded") or status == 429:
        return AccountProblem("Google Drive asked Reelio to slow down.", "Nothing to do. Reelio waits a little and continues.", reason, 30, "quota")
    if status == 401 or reason in ("authError", "invalid_grant"):
        return AccountProblem("Google says this login expired or was revoked.", "Open Accounts, tap Google, then Reconnect.", reason, 0, "token")
    if status == 403 and (reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT") or "scope" in low or "insufficient" in low):
        return AccountProblem("This Google login is not allowed to save files into Drive yet.",
                              "Open Accounts, tap Google, then Reconnect and tick the Drive permission. Videos already in the list stay waiting.", reason, 0, "setup")
    if status == 404:
        return ItemProblem("Drive could not find the target folder.",
                           "Reelio can only use folders it made itself. Leave the folder ID empty in the Save to Drive page so Reelio makes the folder, then tap Retry.", reason)
    return ItemProblem(f"Google Drive refused: {msg[:180] or reason or status}", "Tap Retry, or open Help for a full check.", reason)


def _q(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def _list(auth, q, fields="files(id,name)"):
    try:
        r = http("GET", f"{API()}/files", headers=auth.headers(), retries=3,
                 params={"q": q, "fields": fields, "pageSize": 20, "spaces": "drive", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    except HttpFail as e:
        raise ItemProblem(f"Could not reach Google Drive: {e}", "Usually temporary. Reelio retries.")
    if r.status_code >= 400:
        raise drive_error(r.status_code, _j(r))
    return _j(r).get("files") or []


def ensure_folder(auth, name, parent=None):
    """Find (or make) a folder called `name` inside `parent` ('root' = My Drive). Returns its id."""
    parent = parent or "root"
    name = (name or "").strip() or "Reelio Downloads"
    hit = _list(auth, f"mimeType='{FOLDER}' and name='{_q(name)}' and '{_q(parent)}' in parents and trashed=false")
    if hit:
        return hit[0]["id"]
    try:
        r = http("POST", f"{API()}/files", headers=dict(auth.headers(), **{"Content-Type": "application/json"}), retries=3,
                 params={"fields": "id", "supportsAllDrives": "true"}, data=json.dumps({"name": name, "mimeType": FOLDER, "parents": [parent]}))
    except HttpFail as e:
        raise ItemProblem(f"Could not reach Google Drive: {e}", "Usually temporary. Reelio retries.")
    if r.status_code >= 400:
        raise drive_error(r.status_code, _j(r))
    return _j(r)["id"]


def folder_exists(auth, fid):
    try:
        r = http("GET", f"{API()}/files/{fid}", headers=auth.headers(), retries=2, params={"fields": "id,trashed,mimeType", "supportsAllDrives": "true"})
    except HttpFail:
        return True              # cannot tell: assume it is still there rather than making a second folder
    if r.status_code == 404:
        return False
    if r.status_code >= 400:
        raise drive_error(r.status_code, _j(r))
    j = _j(r)
    return not j.get("trashed") and j.get("mimeType") == FOLDER


def find_by_src(auth, parent, src_key):
    """The Drive file id we already saved for this source video in this folder, or ''."""
    hit = _list(auth, f"appProperties has {{ key='srcId' and value='{_q(src_key)}' }} and '{_q(parent)}' in parents and trashed=false")
    return hit[0]["id"] if hit else ""


def upload(auth, path, name, parent, props, deadline, mime="video/mp4"):
    """Resumable upload in chunks. After any hiccup we ask Drive how much arrived and continue from there."""
    size = os.path.getsize(path)
    body = {"name": name, "parents": [parent], "appProperties": {k: str(v)[:120] for k, v in (props or {}).items()}}
    try:
        r = http("POST", f"{UPLOAD()}/files", retries=3, params={"uploadType": "resumable", "supportsAllDrives": "true", "fields": "id"},
                 headers=dict(auth.headers(), **{"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size), "Content-Type": "application/json; charset=UTF-8"}),
                 data=json.dumps(body))
    except HttpFail as e:
        raise ItemProblem(f"Could not reach Google Drive: {e}", "Usually temporary. Reelio retries.")
    if r.status_code >= 400:
        raise drive_error(r.status_code, _j(r))
    session = r.headers.get("Location")
    if not session:
        raise ItemProblem("Google Drive did not start the upload.", "Retry later.")
    want = int(os.environ.get("REELIO_DRIVE_CHUNK", 64 * 1024 * 1024))
    chunk = max(GRAIN, (want // GRAIN) * GRAIN)
    offset, bad = 0, 0
    if size == 0:
        raise ItemProblem("The downloaded file is empty.", "Tap Retry.")
    with open(path, "rb") as f:
        while offset < size:
            if now() > deadline + datetime.timedelta(minutes=20):
                raise ItemProblem("The upload did not finish before this run ran out of time.", "Reelio tries this video again in the next run.")
            end = min(offset + chunk, size) - 1
            f.seek(offset)
            data = f.read(end - offset + 1)
            try:
                resp = http("PUT", session, retries=1, timeout=(30, 600), data=data,
                            headers={"Content-Length": str(len(data)), "Content-Range": f"bytes {offset}-{end}/{size}", "Content-Type": mime})
            except HttpFail:
                resp = None
            if resp is not None and resp.status_code in (200, 201):
                return _j(resp).get("id", "")
            if resp is not None and resp.status_code == 308:
                new = _next_offset(resp, offset, end)
                bad = 0 if new > offset else bad + 1
                offset = new
                if bad > 8:
                    raise ItemProblem("The upload to Drive made no progress.", "Reelio tries this video again later. Nothing is saved twice.")
                continue
            if resp is not None and 400 <= resp.status_code < 500 and resp.status_code not in (404, 408, 429):
                raise drive_error(resp.status_code, _j(resp))
            bad += 1                                  # network trouble, 5xx or a lost session: ask how much arrived
            if bad > 8:
                raise ItemProblem("The upload to Drive kept failing.", "Reelio tries this video again later. Nothing is saved twice.")
            sleep(min(60, 3 * bad * bad))
            try:
                q = http("PUT", session, retries=1, headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
            except HttpFail:
                continue
            if q.status_code in (200, 201):
                return _j(q).get("id", "")
            if q.status_code == 308:
                offset = _next_offset(q, offset, offset - 1)
    raise ItemProblem("Google Drive did not confirm the upload.", "Reelio checks the folder before trying again, so nothing is saved twice.")


def _next_offset(resp, offset, sent_end):
    m = re.match(r"bytes=0-(\d+)", resp.headers.get("Range", "") or "")
    return int(m.group(1)) + 1 if m else (sent_end + 1 if sent_end >= offset else 0)
