import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, get_args

from gisting.eval.dataclass_json import DecodeError, Pattern, decode_as

Label = Annotated[str, Pattern(r"\S")]
Mode = Literal["full", "gist"]


class EpochMismatch(ValueError):
    pass


def parse_mode(value: object) -> Mode | None:
    return next((mode for mode in get_args(Mode) if value == mode), None)


@dataclass(frozen=True)
class Epoch:
    backend_id: Label
    rules_version: Label
    mode: Mode
    metrics: dict[str, float | None]

    @property
    def key(self) -> tuple[str, str, str]:
        return self.backend_id, self.rules_version, self.mode


@dataclass(frozen=True)
class Baseline:
    version: Literal[1]
    epochs: tuple[Epoch, ...]

    def epoch(self, backend_id: str, rules_version: str, mode: str) -> Epoch | None:
        wanted = (backend_id, rules_version, mode)
        return next((item for item in self.epochs if item.key == wanted), None)

    @staticmethod
    def parse(document: object) -> "Baseline":
        baseline = decode_as(Baseline, document)
        keys = [item.key for item in baseline.epochs]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            message = f"duplicate epochs {repeated}"
            raise DecodeError(message)
        return baseline


def load_baseline(path: Path) -> Baseline:
    return Baseline.parse(json.loads(path.read_text(encoding="utf-8")))


def metric_delta(old: Epoch, new: Epoch, metric: str) -> float | None:
    if old.key != new.key:
        message = f"epochs {old.key} and {new.key} are not comparable"
        raise EpochMismatch(message)
    before, after = old.metrics.get(metric), new.metrics.get(metric)
    return None if before is None or after is None else after - before


def baseline_problems(baseline: Baseline, registered: frozenset[str]) -> list[str]:
    return [
        f"epoch {item.backend_id}/{item.rules_version}/{item.mode} has unregistered metric {name}"
        for item in baseline.epochs
        for name in sorted(set(item.metrics) - registered)
    ]
