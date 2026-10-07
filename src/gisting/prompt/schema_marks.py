from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    regex: str


@dataclass(frozen=True)
class MaxItems:
    count: int


@dataclass(frozen=True)
class MaxLength:
    chars: int
