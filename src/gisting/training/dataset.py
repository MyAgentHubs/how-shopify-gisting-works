import random
from dataclasses import replace

from gisting.eval.case import FIRST
from gisting.prompt.messages import UserMessage
from gisting.shopify.jsonvalue import JsonObject, required_int, required_object
from gisting.tools.policy import load_policy
from gisting.training.draw import Draw, fill, rotation
from gisting.training.multi_turn import multi_turn_samples
from gisting.training.samples import Sample
from gisting.training.scenarios import OrderEntry, load_entries, split_orders
from gisting.training.templates import (
    SPLITS,
    as_float,
    families_of,
    load_document,
    quota_of,
    section,
)

NEEDS_ORDER = {"order_full": True, "order_no_email": True, "order_no_number": False}
NEEDS_EMAIL = {"order_full": True, "order_no_email": False, "order_no_number": True}
HOURS = 24
POLICY_GROUP = "policy_first_call"
POLICY_MARK = "p"


def first_call(
    draw: Draw, category: str, group: str = "first_call", mark: str = ""
) -> list[Sample]:
    node = section(draw.document, group, category)
    families = families_of(required_object(node, "families"), draw.split)
    rotating, entries = rotation(families, draw.rng), draw.entries()
    samples: list[Sample] = []
    for index in range(quota_of(node).of(draw.split)):
        family, template = next(rotating)
        entry = next(entries) if NEEDS_ORDER.get(category, False) else None
        order = draw.order_text(entry) if entry else None
        email = draw.email() if NEEDS_EMAIL.get(category, False) else None
        user = UserMessage(fill(template, order, email))
        name = f"{draw.split}-{FIRST}-{category}-{mark}{index:03d}"
        number = entry.number if entry else None
        samples.append(
            Sample(name, draw.split, category, family.name, FIRST, None, number, email, (user,))
        )
    return samples


def policy_samples(draw: Draw, seed: int) -> list[Sample]:
    own = replace(draw, rng=random.Random(f"{seed}:{draw.split}:{POLICY_GROUP}"))
    samples: list[Sample] = []
    for category in sorted(section(draw.document, POLICY_GROUP)):
        samples.extend(first_call(own, category, POLICY_GROUP, POLICY_MARK))
    return samples


def build_split(
    document: JsonObject, pool: list[OrderEntry], split: str, seed: int
) -> list[Sample]:
    draw = Draw(split, random.Random(f"{seed}:{split}"), document, pool, load_policy())
    samples: list[Sample] = []
    for category in sorted(section(document, "first_call")):
        samples.extend(first_call(draw, category))
    samples.extend(multi_turn_samples(draw))
    samples.extend(policy_samples(draw, seed))
    return samples


def build_dataset() -> list[Sample]:
    document = load_document()
    seed = required_int(document, "seed")
    fraction = as_float(document.get("dev_order_fraction"))
    pools = split_orders(load_entries(), fraction, seed)
    return [s for split in SPLITS for s in build_split(document, pools[split], split, seed)]
