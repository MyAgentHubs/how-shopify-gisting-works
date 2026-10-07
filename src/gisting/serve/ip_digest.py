import re

from gisting.serve.contract import RequestRejected

IP_DIGEST_HEADER = "x-gisting-ip-digest"


def read_ip_digest(values: list[str], pattern: str) -> str | None:
    if not values:
        return None
    if len(values) > 1:
        raise RequestRejected("invalid_request")
    value = values[0]
    if not value:
        return None
    if re.fullmatch(pattern, value) is None:
        raise RequestRejected("invalid_request")
    return value
