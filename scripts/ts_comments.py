import re
from collections.abc import Iterator
from dataclasses import dataclass

REGEX_PREFIX_CHARS = frozenset("(,=:[!&|?{};+-*%<>~^")
REGEX_PREFIX_WORDS = frozenset({"return", "typeof", "case", "in", "of", "delete", "void", "throw"})
WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class TsComment:
    line: int
    text: str
    is_block: bool
    whole_line: bool


def skip_quoted(source: str, index: int) -> int:
    quote = source[index]
    index += 1
    while index < len(source) and source[index] not in (quote, "\n"):
        index += 2 if source[index] == "\\" else 1
    return index + 1


def skip_regex(source: str, index: int) -> int:
    index += 1
    in_class = False
    while index < len(source) and source[index] != "\n":
        char = source[index]
        if char == "\\":
            index += 1
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return index + 1
        index += 1
    return index


def template_body(source: str, index: int) -> tuple[int, bool]:
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == "`":
            return index + 1, False
        elif source.startswith("${", index):
            return index + 2, True
        else:
            index += 1
    return index, False


def regex_allowed(source: str, index: int) -> bool:
    before = source[:index].rstrip()
    if not before:
        return True
    if before[-1] in REGEX_PREFIX_CHARS:
        return True
    word = WORD.search(before)
    return word is not None and word.group(0) in REGEX_PREFIX_WORDS


def block_end(source: str, index: int) -> int:
    end = source.find("*/", index + 2)
    return len(source) if end < 0 else end + 2


def line_end(source: str, index: int) -> int:
    end = source.find("\n", index)
    return len(source) if end < 0 else end


def make_comment(source: str, start: int, end: int, is_block: bool) -> TsComment:
    line_start = source.rfind("\n", 0, start) + 1
    return TsComment(
        line=source.count("\n", 0, start) + 1,
        text=source[start:end],
        is_block=is_block,
        whole_line=not source[line_start:start].strip(),
    )


def slash_step(source: str, index: int) -> tuple[int, TsComment | None]:
    following = source[index + 1 : index + 2]
    if following == "/":
        end = line_end(source, index)
        return end, make_comment(source, index, end, False)
    if following == "*":
        end = block_end(source, index)
        return end, make_comment(source, index, end, True)
    if regex_allowed(source, index):
        return skip_regex(source, index), None
    return index + 1, None


def ts_comments(source: str) -> Iterator[TsComment]:
    index = 0
    braces: list[int] = []
    while index < len(source):
        char = source[index]
        if char == "/":
            index, comment = slash_step(source, index)
            if comment is not None:
                yield comment
        elif char in "'\"":
            index = skip_quoted(source, index)
        elif char == "`" or (char == "}" and braces and braces[-1] == 0):
            index, entered = template_body(source, index + 1)
            if char == "}":
                braces.pop()
            if entered:
                braces.append(0)
        else:
            if braces and char in "{}":
                braces[-1] += 1 if char == "{" else -1
            index += 1
