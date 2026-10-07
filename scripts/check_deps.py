#!/usr/bin/env python3
import json
import re
import sys
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import guardlib
from guardlib import Violation

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SEPARATORS = re.compile(r"[-_.]+")


def canonical(name: str) -> str:
    return SEPARATORS.sub("-", name).lower()


def requirement_names(entries: Sequence[Any]) -> Iterator[str]:
    for entry in entries:
        match = NAME.match(entry) if isinstance(entry, str) else None
        if match:
            yield canonical(match.group())


def declared(pyproject: dict[str, Any]) -> set[str]:
    project: dict[str, Any] = pyproject.get("project", {})
    names = set(requirement_names(project.get("dependencies", [])))
    for entries in project.get("optional-dependencies", {}).values():
        names.update(requirement_names(entries))
    for entries in pyproject.get("dependency-groups", {}).values():
        names.update(requirement_names(entries))
    return names


def listed(registry: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in registry.get("dependency", []):
        name = entry.get("name")
        if isinstance(name, str):
            reason = entry.get("reason")
            result[canonical(name)] = reason.strip() if isinstance(reason, str) else ""
    return result


def package_names(package: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        entries: dict[str, Any] = package.get(section, {})
        names.update(canonical(name) for name in entries)
    return names


def package_violations(root: Path, registry: dict[str, str]) -> list[Violation]:
    found: list[Violation] = []
    for path in guardlib.iter_files(root, ("package.json",)):
        package = json.loads(path.read_text(encoding="utf-8"))
        message = "dependency {} is not listed in deps.toml"
        found.extend(
            Violation(guardlib.rel(root, path), 1, message.format(name))
            for name in sorted(package_names(package) - registry.keys())
        )
    return found


def line_of(text: str, name: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("name") and name in canonical(line):
            return number
    return 1


def find_violations(root: Path) -> list[Violation]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if not (root / "deps.toml").is_file():
        return [Violation("deps.toml", 1, "file is missing")]
    registry_text = (root / "deps.toml").read_text(encoding="utf-8")
    registry = listed(tomllib.loads(registry_text))
    found: list[Violation] = []
    for name in sorted(declared(pyproject) - registry.keys()):
        found.append(
            Violation("pyproject.toml", 1, f"dependency {name} is not listed in deps.toml")
        )
    found.extend(package_violations(root, registry))
    for name, reason in registry.items():
        if not reason:
            line = line_of(registry_text, name)
            found.append(Violation("deps.toml", line, f"dependency {name} has an empty reason"))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Check that every dependency has a stated reason.", argv)
    return guardlib.report(find_violations(root))


if __name__ == "__main__":
    sys.exit(main())
