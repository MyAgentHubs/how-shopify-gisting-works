from gisting.shopify.graphql import is_packaged_query
from gisting.shopify.results import Cause, NotExecuted, Result
from gisting.shopify.transport import Request, Transport


class ReadOnlyTransport:
    def __init__(self, inner: Transport) -> None:
        self._inner = inner

    @property
    def store(self) -> str:
        return self._inner.store

    def execute(self, request: Request) -> Result:
        if not is_packaged_query(request.name, request.document):
            return NotExecuted(Cause.READ_ONLY, request.name)
        return self._inner.execute(request)
