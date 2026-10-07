import copy
import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace

from gisting.shopify.graphql import is_packaged_query
from gisting.shopify.http_token import HTTP_OK, TokenSource
from gisting.shopify.http_wire import Clamp, Reply, send, tail, unclamped
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.results import (
    Cause,
    GraphQLError,
    NotExecuted,
    Ok,
    Result,
    Uncertain,
    classify_payload,
)
from gisting.shopify.target import API_VERSION, DEV_STORE, StoreNotAllowed
from gisting.shopify.transport import Request

HTTP_REDIRECT_FIRST = 300
HTTP_REDIRECT_LAST = 399
HTTP_UNAUTHORIZED = 401
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500
THROTTLED = "THROTTLED"


@dataclass(frozen=True)
class HttpConfig:
    store: str = DEV_STORE
    base_url: str | None = None
    timeout: float = 30.0
    query_attempts: int = 3
    backoff_seconds: float = 1.0
    max_wait_seconds: float = 60.0


@dataclass
class Pace:
    pause: float = 0.0


@dataclass(frozen=True)
class Attempt:
    result: Result
    wait: float | None = None


def number(value: Json) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def retry_after(reply: Reply) -> float | None:
    raw = reply.headers.get("Retry-After")
    try:
        seconds = float(raw) if raw is not None else -1.0
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def cost_of(payload: Json) -> JsonObject:
    extensions = payload.get("extensions") if isinstance(payload, dict) else None
    cost = extensions.get("cost") if isinstance(extensions, dict) else None
    return cost if isinstance(cost, dict) else {}


def throttle_status(payload: Json) -> JsonObject | None:
    status = cost_of(payload).get("throttleStatus")
    return status if isinstance(status, dict) else None


def budget_wait(payload: Json) -> float:
    status = throttle_status(payload) or {}
    needed = number(cost_of(payload).get("requestedQueryCost"))
    available = number(status.get("currentlyAvailable"))
    rate = number(status.get("restoreRate"))
    if needed is None or available is None or not rate or available >= needed:
        return 0.0
    return (needed - available) / rate


def error_code(error: JsonObject) -> Json:
    extensions = error.get("extensions")
    return extensions.get("code") if isinstance(extensions, dict) else None


def is_throttled(result: Result) -> bool:
    if not isinstance(result, GraphQLError):
        return False
    return any(error_code(error) == THROTTLED for error in result.errors)


def worth_retrying(result: Result) -> bool:
    if isinstance(result, NotExecuted):
        return result.cause in {Cause.NETWORK, Cause.RATE_LIMITED}
    return isinstance(result, Uncertain) or is_throttled(result)


class HttpTransport:
    def __init__(
        self,
        client_secret: str,
        config: HttpConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        config = config or HttpConfig()
        if config.store != DEV_STORE:
            raise StoreNotAllowed(config.store)
        self._config = config
        self._base = (config.base_url or f"https://{config.store}").rstrip("/")
        self._sleep = sleep
        self._tokens = TokenSource(self._base, client_secret, config.timeout, clock)
        self._pace = Pace()
        self._clamp: Clamp = unclamped

    @property
    def store(self) -> str:
        return self._config.store

    def bounded(self, clamp: Clamp) -> "HttpTransport":
        view = copy.copy(self)
        view._clamp = clamp
        return view

    def execute(self, request: Request) -> Result:
        retryable = is_packaged_query(request.name, request.document)
        attempts = self._config.query_attempts if retryable else 1
        attempt = self._once(request)
        for number_done in range(1, attempts):
            if not worth_retrying(attempt.result):
                break
            wait = attempt.wait
            if wait is None:
                wait = self._config.backoff_seconds * 2 ** (number_done - 1)
            self._sleep(self._clamp(min(wait, self._config.max_wait_seconds)))
            attempt = self._once(request)
        return attempt.result

    def _once(self, request: Request) -> Attempt:
        if self._pace.pause > 0:
            owed = min(self._pace.pause, self._config.max_wait_seconds)
            slept = self._clamp(owed)
            self._sleep(slept)
            self._pace.pause = owed - slept
        reply = self._post(request)
        if not isinstance(reply, Reply):
            return Attempt(reply)
        return self._interpret(reply)

    def _post(self, request: Request) -> Reply | NotExecuted | Uncertain:
        reply: Reply | NotExecuted | Uncertain = NotExecuted(Cause.AUTH, "no attempt made")
        for _ in range(2):
            token = self._tokens.get(self._clamp)
            if isinstance(token, NotExecuted):
                return token
            reply = send(self._graphql_request(request, token), self._config.timeout, self._clamp)
            if not (isinstance(reply, Reply) and reply.status == HTTP_UNAUTHORIZED):
                return reply
            self._tokens.invalidate()
        return reply

    def _graphql_request(self, request: Request, token: str) -> urllib.request.Request:
        body = json.dumps({"query": request.document, "variables": request.variables})
        return urllib.request.Request(
            f"{self._base}/admin/api/{API_VERSION}/graphql.json",
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Shopify-Access-Token": token,
            },
            method="POST",
        )

    def _interpret(self, reply: Reply) -> Attempt:
        if reply.status == HTTP_TOO_MANY_REQUESTS:
            wait = retry_after(reply)
            detail = "" if wait is None else f"retry-after {wait:g}s"
            return Attempt(NotExecuted(Cause.RATE_LIMITED, detail), wait)
        if reply.status == HTTP_UNAUTHORIZED:
            return Attempt(NotExecuted(Cause.AUTH, "graphql HTTP 401 after token refresh"))
        if HTTP_REDIRECT_FIRST <= reply.status <= HTTP_REDIRECT_LAST:
            return Attempt(NotExecuted(Cause.HTTP_STATUS, f"HTTP {reply.status}: redirect refused"))
        if reply.status >= HTTP_SERVER_ERROR:
            body = self._tokens.scrub(tail(reply.body))
            return Attempt(Uncertain(f"HTTP {reply.status}: {body}"))
        try:
            payload: Json = json.loads(reply.body)
        except ValueError:
            return self._unreadable(reply)
        return Attempt(self._classify(payload))

    def _unreadable(self, reply: Reply) -> Attempt:
        if reply.status == HTTP_OK:
            return Attempt(Uncertain("HTTP 200 with unreadable JSON body"))
        body = self._tokens.scrub(tail(reply.body))
        return Attempt(NotExecuted(Cause.HTTP_STATUS, f"HTTP {reply.status}: {body}"))

    def _classify(self, payload: Json) -> Result:
        self._pace.pause = budget_wait(payload)
        result = classify_payload(payload)
        status = throttle_status(payload)
        if isinstance(result, Ok | GraphQLError):
            return replace(result, throttle=status)
        return result
