import http.client
import math
import re
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from typing import Protocol, cast

from gisting.shopify.http_watch import Watchdog, opener_for
from gisting.shopify.results import Cause, NotExecuted, Uncertain

TAIL_CHARS = 200
CHUNK_BYTES = 8192
Clamp = Callable[[float], float]
PRE_CONNECT_ERRORS = (socket.gaierror, ConnectionRefusedError, ssl.SSLCertVerificationError)
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Reply:
    status: int
    headers: Message
    body: bytes


def unclamped(wanted: float) -> float:
    return wanted


class Chunked(Protocol):
    length: int | None

    def read1(self, amount: int, /) -> bytes: ...


def read_within(stream: Chunked, clamp: Clamp, timeout: float) -> bytes:
    chunks: list[bytes] = []
    while chunk := stream.read1(CHUNK_BYTES):
        chunks.append(chunk)
        clamp(timeout)
    if stream.length:
        raise http.client.IncompleteRead(b"".join(chunks), stream.length)
    return b"".join(chunks)


def tail(body: bytes) -> str:
    return WHITESPACE.sub(" ", body.decode("utf-8", errors="replace")).strip()[:TAIL_CHARS]


def read_error_body(error: urllib.error.HTTPError, clamp: Clamp, timeout: float) -> bytes:
    try:
        return read_within(cast(Chunked, error), clamp, timeout)
    except (OSError, http.client.HTTPException):
        return b""


def exchange(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    timeout: float,
    clamp: Clamp,
) -> Reply | NotExecuted | Uncertain:
    try:
        with opener.open(request, timeout=timeout) as response:
            body = read_within(cast(Chunked, response), clamp, timeout)
            return Reply(response.status, response.headers, body)
    except urllib.error.HTTPError as error:
        return Reply(error.code, error.headers, read_error_body(error, clamp, timeout))
    except urllib.error.URLError as error:
        if isinstance(error.reason, PRE_CONNECT_ERRORS):
            return NotExecuted(Cause.NETWORK, type(error.reason).__name__)
        return Uncertain(f"{type(error.reason).__name__}: {error.reason}")
    except (OSError, http.client.HTTPException) as error:
        return Uncertain(f"{type(error).__name__}: {error}")


def send(
    request: urllib.request.Request, timeout: float, clamp: Clamp = unclamped
) -> Reply | NotExecuted | Uncertain:
    left = clamp(math.inf)
    with Watchdog(left) as watch:
        outcome = exchange(opener_for(watch), request, min(timeout, left), clamp)
    if watch.fired:
        clamp(timeout)
        return Uncertain("deadline passed with the exchange in flight")
    if not isinstance(outcome, Reply):
        clamp(timeout)
    return outcome
