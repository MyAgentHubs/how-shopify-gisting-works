import re
from importlib import resources

SUFFIX = ".graphql"
DOCUMENT_NAME = re.compile(r"[a-z][a-z0-9_]*")
QUERY_KEYWORD = "query"


class UnknownDocument(LookupError):
    pass


def load_document(name: str) -> str:
    if not DOCUMENT_NAME.fullmatch(name):
        raise UnknownDocument(name)
    resource = resources.files("gisting.shopify").joinpath("graphql", name + SUFFIX)
    if not resource.is_file():
        raise UnknownDocument(name)
    return resource.read_text(encoding="utf-8")


def is_mutation(document: str) -> bool:
    return document.lstrip().startswith("mutation")


def is_packaged_query(name: str, document: str) -> bool:
    try:
        packaged = load_document(name)
    except UnknownDocument:
        return False
    return document == packaged and packaged.startswith(QUERY_KEYWORD)
