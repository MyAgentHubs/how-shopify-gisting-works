import hmac

from gisting.shopify.order_name import InvalidOrderName, canonical_order_name
from gisting.tools.outcomes import Malformed
from gisting.tools.policy import LookupPolicy

ENCODING = "utf-8"


def parse_order_name(raw: str) -> str | Malformed:
    try:
        digits = canonical_order_name(raw).removeprefix("#")
    except InvalidOrderName:
        return Malformed()
    if not digits.isascii():
        return Malformed()
    return f"#{int(digits)}"


def in_range(name: str, policy: LookupPolicy) -> bool:
    return policy.order_min <= int(name.removeprefix("#")) <= policy.order_max


def email_matches(expected: str, supplied: str) -> bool:
    return hmac.compare_digest(
        expected.encode(ENCODING, "surrogatepass"), supplied.encode(ENCODING, "surrogatepass")
    )
