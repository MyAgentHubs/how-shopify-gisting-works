import time
from collections.abc import Callable
from typing import Protocol

from gisting.shopify.order_state import OrderState


class OrderCache(Protocol):
    def get(self, order_name: str) -> OrderState | None: ...

    def put(self, order_name: str, order: OrderState) -> None: ...


class InMemoryOrderCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, OrderState]] = {}

    def get(self, order_name: str) -> OrderState | None:
        entry = self._entries.get(order_name)
        if entry is None:
            return None
        stored_at, order = entry
        if self._clock() - stored_at >= self._ttl:
            del self._entries[order_name]
            return None
        return order

    def put(self, order_name: str, order: OrderState) -> None:
        self._entries[order_name] = (self._clock(), order)
