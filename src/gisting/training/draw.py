import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from gisting.shopify.jsonvalue import JsonObject, required_int
from gisting.tools.outcomes import Found, Locked, LookupOutcome, NotFound, UpstreamError
from gisting.tools.policy import LookupPolicy
from gisting.training.emails import make_email
from gisting.training.scenarios import OrderEntry, build_facts
from gisting.training.templates import Family, forms, section

HOURS = 24


@dataclass
class Draw:
    split: str
    rng: random.Random
    document: JsonObject
    pool: list[OrderEntry]
    policy: LookupPolicy

    def entries(self, scenario: str | None = None) -> Iterator[OrderEntry]:
        usable = [e for e in self.pool if scenario in (None, e.scenario)]
        while True:
            self.rng.shuffle(usable)
            yield from usable

    def order_text(self, entry: OrderEntry) -> str:
        number = entry.number.removeprefix("#")
        return self.rng.choice(forms(self.document)).format(n=number)

    def anchor(self) -> datetime:
        spec = section(self.document, "anchor_dates")
        first = datetime.fromisoformat(str(spec["first"]))
        offset = self.rng.randrange(required_int(spec, "days") * HOURS)
        return first + timedelta(hours=offset)

    def email(self) -> str:
        return make_email(self.rng, self.document)


def rotation(families: tuple[Family, ...], rng: random.Random) -> Iterator[tuple[Family, str]]:
    pairs = [(family, text) for family in families for text in family.templates]
    while True:
        rng.shuffle(pairs)
        yield from pairs


def fill(template: str, order: str | None, email: str | None) -> str:
    return template.replace("{order}", order or "").replace("{email}", email or "")


def outcome_for(draw: Draw, entry: OrderEntry, kind: str, anchor: datetime) -> LookupOutcome:
    if kind == "found":
        return Found(build_facts(entry, anchor, draw.policy))
    return {"no_match": NotFound(), "unavailable": UpstreamError("graphql_error")}.get(
        kind, Locked()
    )
