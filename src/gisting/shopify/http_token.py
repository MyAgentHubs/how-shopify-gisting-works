import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable

from gisting.shopify.http_wire import Clamp, Reply, send, tail, unclamped
from gisting.shopify.jsonvalue import Json
from gisting.shopify.results import Cause, NotExecuted, Uncertain
from gisting.shopify.target import CLIENT_ID

EXPIRY_MARGIN_SECONDS = 60.0
DEFAULT_LIFETIME_SECONDS = 3600.0
REDACTED = "***"
HTTP_OK = 200


class TokenSource:
    def __init__(
        self,
        base_url: str,
        client_secret: str,
        timeout: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = f"{base_url}/admin/oauth/access_token"
        self._client_secret = client_secret
        self._timeout = timeout
        self._clock = clock
        self._token = ""
        self._expires_at = 0.0

    def scrub(self, text: str) -> str:
        for secret in (self._client_secret, self._token):
            if secret:
                text = text.replace(secret, REDACTED)
        return text

    def invalidate(self) -> None:
        self._token = ""
        self._expires_at = 0.0

    def get(self, clamp: Clamp = unclamped) -> str | NotExecuted:
        if self._token and self._clock() < self._expires_at - EXPIRY_MARGIN_SECONDS:
            return self._token
        return self._exchange(clamp)

    def _exchange(self, clamp: Clamp) -> str | NotExecuted:
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": self._client_secret,
        })
        request = urllib.request.Request(
            self._url,
            data=form.encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        reply = send(request, self._timeout, clamp)
        if isinstance(reply, NotExecuted):
            return reply
        if isinstance(reply, Uncertain):
            return NotExecuted(Cause.NETWORK, self.scrub(reply.reason))
        return self._accept(reply)

    def _accept(self, reply: Reply) -> str | NotExecuted:
        if reply.status != HTTP_OK:
            body = self.scrub(tail(reply.body))
            return NotExecuted(Cause.AUTH, f"token exchange HTTP {reply.status}: {body}")
        try:
            payload: Json = json.loads(reply.body)
        except ValueError:
            return NotExecuted(Cause.AUTH, "token exchange returned unreadable JSON")
        fields = payload if isinstance(payload, dict) else {}
        token = fields.get("access_token")
        if not isinstance(token, str) or not token:
            return NotExecuted(Cause.AUTH, "token exchange returned no access_token")
        lifetime = fields.get("expires_in")
        seconds = lifetime if isinstance(lifetime, int | float) else DEFAULT_LIFETIME_SECONDS
        self._token = token
        self._expires_at = self._clock() + seconds
        return token
