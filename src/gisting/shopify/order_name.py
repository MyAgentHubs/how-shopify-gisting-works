import re

ORDER_NAME = re.compile(r"#?(\d{1,12})")


class InvalidOrderName(ValueError):
    pass


def canonical_order_name(raw: str) -> str:
    match = ORDER_NAME.fullmatch(raw.strip())
    if match is None:
        raise InvalidOrderName(raw)
    return f"#{match.group(1)}"
