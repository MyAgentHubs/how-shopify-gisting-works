from dataclasses import dataclass
from typing import Protocol

from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.results import Result


@dataclass(frozen=True)
class Request:
    name: str
    document: str
    variables: JsonObject


class Transport(Protocol):
    @property
    def store(self) -> str: ...

    def execute(self, request: Request) -> Result: ...
