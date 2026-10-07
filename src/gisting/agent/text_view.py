import re
import unicodedata

EMPHASIS = re.compile(r"[*_`]+")
FORMAT_CATEGORY = "Cf"
SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def plain(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def canonical(text: str) -> str:
    visible = "".join(c for c in plain(text) if unicodedata.category(c) != FORMAT_CATEGORY)
    return "\n".join(visible.translate(SMART_QUOTES).splitlines())


def views(text: str) -> tuple[str, ...]:
    canon = canonical(text)
    return text, canon, EMPHASIS.sub("", canon)
