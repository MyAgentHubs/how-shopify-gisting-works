import pytest

from gisting.shopify import graphql
from gisting.shopify.graphql import UnknownDocument, load_document

PACKAGED_NAMES = ["order_state", "tags_add", "order_update"]
REJECTED_NAMES = [
    "order_state/",
    "order_state\n",
    "order_state.x",
    "order_state/../order_state",
    "../order_state",
    "Order_state",
    "_order_state",
    "order-state",
    "",
]
DOCUMENT = "query { shop { name } }"


class EveryFileExists:
    def joinpath(self, *_parts: str) -> "EveryFileExists":
        return self

    def is_file(self) -> bool:
        return True

    def read_text(self, encoding: str) -> str:
        assert encoding
        return DOCUMENT


@pytest.fixture
def every_file_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    def files(_package: str) -> EveryFileExists:
        return EveryFileExists()

    monkeypatch.setattr(graphql.resources, "files", files)


@pytest.mark.parametrize("name", PACKAGED_NAMES)
def test_a_packaged_document_name_loads(name: str) -> None:
    assert load_document(name).strip()


@pytest.mark.parametrize("name", REJECTED_NAMES)
def test_a_name_that_is_not_wholly_a_document_name_is_refused(name: str) -> None:
    with pytest.raises(UnknownDocument):
        load_document(name)


@pytest.mark.usefixtures("every_file_exists")
@pytest.mark.parametrize("name", REJECTED_NAMES)
def test_the_name_check_stands_without_the_file_check(name: str) -> None:
    with pytest.raises(UnknownDocument):
        load_document(name)


@pytest.mark.usefixtures("every_file_exists")
def test_a_plain_name_passes_the_name_check() -> None:
    assert load_document("anything_plain") == DOCUMENT
