"""Plain-language errors. Every failure becomes (what happened, how to fix it) and a scope:
   ItemProblem    -> only this video is affected (counts toward its 3 tries)
   AccountProblem -> this connected account is paused for a while; everything else keeps running
"""
from .util import scrub


class Problem(Exception):
    scope = "item"

    def __init__(self, msg, fix="", code=None, cooldown_min=0, kind="error"):
        super().__init__(msg)
        self.msg, self.fix, self.code, self.cooldown_min, self.kind = scrub(msg), fix, code, cooldown_min, kind

    def as_dict(self):
        return {"msg": self.msg, "fix": self.fix, "code": self.code, "kind": self.kind}


class ItemProblem(Problem):
    scope = "item"


class AccountProblem(Problem):
    scope = "account"


class RunLimit(Exception):
    """The run's time budget is used up: stop cleanly, the next scheduled run continues."""


IG_RATE = {4, 17, 32, 613}


def instagram_error(err, status=None):
    """Map an Instagram Graph error dict to a Problem."""
    err = err if isinstance(err, dict) else {"message": str(err)}
    code, sub = err.get("code"), err.get("error_subcode")
    msg = str(err.get("message", "")) or "unknown error"
    low = msg.lower()
    if code == 190 or "access token" in low or "session has expired" in low:
        return AccountProblem("Instagram says this login has expired or was revoked.",
                              "Open Accounts, tap the Instagram account, then Reconnect and paste a new token.", 190, 0, "token")
    if sub == 2207042 or "maximum number of" in low and "posts" in low:
        return AccountProblem("Instagram's 24-hour posting limit for this account is used up.",
                              "Nothing to do. Posting resumes by itself when the limit resets.", sub, 240, "quota")
    if code in IG_RATE or sub == 1349210 or any(k in low for k in ("request limit", "rate limit", "too many calls")):
        return AccountProblem("Instagram is asking us to slow down (app request limit).",
                              "Nothing to do. Reelio waits and tries again by itself.", sub or code, 30, "rate")
    if code in (10, 200) or "permission" in low:
        return AccountProblem("This Instagram login is missing the permission to publish.",
                              "Reconnect and tick 'instagram_business_content_publish' when you generate the token.", code, 0, "permission")
    if sub in (2207026, 2207023, 2207032):
        return ItemProblem("Instagram does not accept this video's format.", "Reelio re-encodes videos; try the Retry button, or pick another fit mode in Look.", sub)
    if sub in (2207003, 2207052, 9004) or "could not be fetched" in low or "timeout" in low:
        return ItemProblem("Instagram could not download the video from our host.", "Usually temporary. Reelio retries on its own; if it keeps happening check Cloudinary in Accounts.", sub)
    if sub == 2207051 or "action is blocked" in low or "spam" in low:
        return AccountProblem("Instagram flagged the posting speed as spam-like.", "Lower 'posts per day' in the flow, and raise the gap between posts.", sub, 360, "spam")
    return ItemProblem(f"Instagram refused this post: {msg[:180]}", "Open Help and tap 'Why is it failing?' for a full check.", sub or code)


def youtube_error(status, body):
    reason, msg = "", ""
    try:
        e = (body or {}).get("error", {})
        msg = e.get("message", "")
        reason = (e.get("errors") or [{}])[0].get("reason", "") or e.get("status", "")
    except Exception:
        pass
    if reason in ("uploadLimitExceeded",):
        return AccountProblem("YouTube's daily upload limit for this channel is reached.", "Nothing to do. Posting resumes tomorrow. New channels can upload only a few videos a day; verify your channel with a phone number to raise it.", reason, 480, "quota")
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        return AccountProblem("YouTube's API allowance for today is used up.", "Nothing to do. It resets daily at midnight Pacific time.", reason, 360, "quota")
    if status == 401 or reason in ("authError", "invalid_grant"):
        return AccountProblem("Google says this login expired or was revoked.", "Open Accounts, tap Google, then Reconnect.", reason, 0, "token")
    if status == 403 and reason in ("forbidden", "insufficientPermissions", "youtubeSignupRequired"):
        return AccountProblem("This Google login can't upload to YouTube.", "Reconnect Google and allow YouTube access; make sure the account has a YouTube channel.", reason, 0, "permission")
    return ItemProblem(f"YouTube refused: {msg[:180] or reason or status}", "Tap Retry, or open Help for a full check.", reason)


def google_error(status, body):
    return youtube_error(status, body)


class SourceProblem(Problem):
    """The place videos come from is unavailable (e.g. YouTube blocks the server). Only this flow waits."""
    scope = "route"
