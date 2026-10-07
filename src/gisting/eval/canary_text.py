import html
import unicodedata
from urllib.parse import unquote

DECODE_ROUNDS = 3
MIN_HEX_TAIL = 8
HEX_DIGITS = frozenset("0123456789abcdef")


def decoded(text: str) -> str:
    for _ in range(DECODE_ROUNDS):
        step = html.unescape(unquote(text))
        if step == text:
            break
        text = step
    return text


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFKC", decoded(text))
    return "".join(char for char in plain if char.isalnum()).casefold()


def needles(canary: str) -> list[str]:
    full, tail = fold(canary), fold(canary.rpartition("-")[2])
    found = [full] if full else []
    if len(tail) >= MIN_HEX_TAIL and set(tail) <= HEX_DIGITS and tail != full:
        found.append(tail)
    return found
