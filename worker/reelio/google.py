"""Google login shared by Drive and YouTube: one refresh token -> short-lived access tokens."""
import time
from .errors import AccountProblem
from .util import http, env_base, HttpFail

TOKEN_URL = lambda: env_base("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")


class GoogleAuth:
    def __init__(self, sec):
        self.sec = sec or {}
        self._tok, self._exp = None, 0

    @property
    def api_key(self):
        return self.sec.get("api_key")

    def headers(self):
        if not self.sec.get("refresh_token"):
            if self.api_key:
                return {}
            raise AccountProblem("Google is not connected.", "Open Accounts and tap Connect next to Google.", kind="setup")
        if self._tok and self._exp - 120 > time.time():
            return {"Authorization": f"Bearer {self._tok}"}
        try:
            r = http("POST", TOKEN_URL(), retries=3, data={"grant_type": "refresh_token", "refresh_token": self.sec["refresh_token"],
                                                      "client_id": self.sec.get("client_id"), "client_secret": self.sec.get("client_secret")})
        except HttpFail as e:
            raise AccountProblem(f"Could not reach Google: {e}", "Usually temporary.", cooldown_min=10, kind="network")
        j = r.json() if r.content else {}
        if "access_token" not in j:
            if j.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client"):
                raise AccountProblem("Google says this login expired or was revoked.",
                                     "Open Accounts, tap Google, then Reconnect. (If your Google app is in 'Testing' mode, logins expire after 7 days; publish the app to fix that for good.)", j.get("error"), 0, "token")
            raise AccountProblem(f"Google login failed: {j.get('error_description') or j.get('error') or r.status_code}", "Open Accounts and reconnect Google.", None, 30)
        self._tok, self._exp = j["access_token"], time.time() + int(j.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._tok}"}
