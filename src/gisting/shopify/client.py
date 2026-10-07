import time
from collections.abc import Callable
from dataclasses import dataclass

from gisting.shopify.graphql import UnknownDocument, is_mutation, load_document
from gisting.shopify.jsonvalue import JsonObject, MalformedResponse, collect_gids, connection_nodes
from gisting.shopify.order_name import canonical_order_name
from gisting.shopify.order_state import OrderState, parse_order, shop_is_dev_store
from gisting.shopify.results import (
    Cause,
    Failure,
    GraphQLError,
    NotExecuted,
    Ok,
    Result,
    Uncertain,
    user_errors,
)
from gisting.shopify.target import BATCH_TAG, DEV_STORE, StoreNotAllowed
from gisting.shopify.transport import Request, Transport

ORDER_STATE_DOCUMENT = "order_state"
READ_ATTEMPTS = 3
READ_RETRY_SECONDS = 5.0


@dataclass(frozen=True)
class Verified:
    order_id: str
    name: str


class AdminClient:
    def __init__(
        self,
        transport: Transport,
        sleep: Callable[[float], None] = time.sleep,
        read_attempts: int = READ_ATTEMPTS,
        retry_seconds: float = READ_RETRY_SECONDS,
    ) -> None:
        if transport.store != DEV_STORE:
            raise StoreNotAllowed(transport.store)
        self._transport = transport
        self._sleep = sleep
        self._read_attempts = read_attempts
        self._retry_seconds = retry_seconds
        self._scopes: dict[str, set[str]] = {}

    def fetch_order(self, raw_name: str) -> OrderState | Failure:
        name = canonical_order_name(raw_name)
        request = Request(
            ORDER_STATE_DOCUMENT, load_document(ORDER_STATE_DOCUMENT), {"query": f"name:{name}"}
        )
        result = self._read(request)
        if not isinstance(result, Ok):
            return result
        try:
            return self._single_order(result.data, name)
        except MalformedResponse as error:
            return Uncertain(f"malformed order response: {error}")

    def writable(self, order: OrderState) -> Verified | NotExecuted:
        if not order.test:
            return NotExecuted(Cause.NOT_TEST_ORDER, order.name)
        if BATCH_TAG not in order.tags:
            return NotExecuted(Cause.MISSING_BATCH_TAG, order.name)
        self._scopes.setdefault(order.id, set()).update(order.gids)
        return Verified(order.id, order.name)

    def write(self, verified: Verified, document_name: str, variables: JsonObject) -> Result:
        prepared = self._preflight(verified, document_name, variables)
        if isinstance(prepared, NotExecuted):
            return prepared
        document, scope = prepared
        result = self._transport.execute(Request(document_name, document, variables))
        if not isinstance(result, Ok):
            return result
        if errors := user_errors(result.data):
            return GraphQLError(errors, user_errors=True, throttle=result.throttle)
        scope.update(collect_gids(result.data))
        return result

    def _preflight(
        self, verified: Verified, document_name: str, variables: JsonObject
    ) -> tuple[str, set[str]] | NotExecuted:
        scope = self._scopes.get(verified.order_id)
        if scope is None:
            return NotExecuted(Cause.UNVERIFIED_ORDER, verified.name)
        try:
            document = load_document(document_name)
        except UnknownDocument:
            return NotExecuted(Cause.UNKNOWN_DOCUMENT, document_name)
        if not is_mutation(document):
            return NotExecuted(Cause.WRONG_DOCUMENT_KIND, document_name)
        targets = collect_gids(variables)
        if not targets or not targets <= scope:
            return NotExecuted(Cause.FOREIGN_ID, ",".join(sorted(targets - scope)))
        return document, scope

    def _read(self, request: Request) -> Result:
        result: Result = Uncertain("no attempt made")
        for attempt in range(self._read_attempts):
            if attempt:
                self._sleep(self._retry_seconds)
            result = self._transport.execute(request)
            if not isinstance(result, Uncertain):
                break
        return result

    def _single_order(self, data: JsonObject, name: str) -> OrderState | Failure:
        if not shop_is_dev_store(data, DEV_STORE):
            return NotExecuted(Cause.WRONG_STORE, name)
        nodes = connection_nodes(data, "orders")
        matches = [node for node in nodes if node.get("name") == name]
        if not matches:
            return NotExecuted(Cause.ORDER_NOT_FOUND, name)
        if len(matches) > 1:
            return NotExecuted(Cause.DUPLICATE_ORDER, name)
        return parse_order(matches[0])
