from collections.abc import Callable
from typing import Protocol

from gisting.serve.deadline import Deadline, DeadlineTransport
from gisting.shopify.client import AdminClient
from gisting.shopify.http_wire import Clamp
from gisting.shopify.readonly import ReadOnlyTransport
from gisting.shopify.results import Result
from gisting.shopify.transport import Request, Transport

ClientFactory = Callable[[Deadline], AdminClient]


class Boundable(Protocol):
    @property
    def store(self) -> str: ...

    def execute(self, request: Request) -> Result: ...

    def bounded(self, clamp: Clamp) -> Transport: ...


def client_factory(
    inner: Boundable, sleep: Callable[[float], None], read_attempts: int, retry_seconds: float
) -> ClientFactory:
    def build(deadline: Deadline) -> AdminClient:
        transport = ReadOnlyTransport(DeadlineTransport(inner.bounded(deadline.clamp), deadline))
        return AdminClient(
            transport,
            lambda seconds: sleep(deadline.clamp(seconds)),
            read_attempts=read_attempts,
            retry_seconds=retry_seconds,
        )

    return build
