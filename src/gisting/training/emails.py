import base64
import hashlib
import random

from gisting.shopify.jsonvalue import Json, JsonObject, required_object, string_list
from gisting.training.templates import as_float

DEMO_LOCAL_LENGTH = 10


def demo_style(rng: random.Random, domain: str) -> str:
    digest = hashlib.sha256(str(rng.random()).encode()).digest()
    local = base64.b32encode(digest).decode().lower()[:DEMO_LOCAL_LENGTH]
    return f"{local}@{domain}"


def customer_style(rng: random.Random, spec: JsonObject) -> str:
    local = rng.choice(string_list(spec, "locals"))
    domain = rng.choice(string_list(spec, "domains"))
    if rng.choice(string_list(spec, "case_variants")) == "title":
        local = local.title()
    return f"{local}@{domain}"


def make_email(rng: random.Random, document: JsonObject) -> str:
    spec = required_object(document, "emails")
    share: Json = spec.get("demo_style_share")
    if rng.random() < as_float(share):
        domain: Json = spec.get("demo_domain")
        return demo_style(rng, str(domain))
    return customer_style(rng, spec)
