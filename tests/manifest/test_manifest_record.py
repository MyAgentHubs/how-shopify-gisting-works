import json
from pathlib import Path

import pytest
from manifest_support import manifest

from gisting.manifest.base_model import read_base_model
from gisting.manifest.record import (
    MANIFEST_FILE,
    ManifestError,
    dump_manifest,
    parse_manifest,
    read_manifest,
    sha256_file,
    write_manifest,
)


def document() -> dict[str, object]:
    return json.loads(dump_manifest(manifest()))


def test_manifest_round_trips_through_its_file(tmp_path: Path) -> None:
    item = manifest()
    write_manifest(tmp_path, item)
    assert read_manifest(tmp_path) == item


def test_manifest_records_every_required_item() -> None:
    assert set(document()) == {
        "schema",
        "run_id",
        "base_model_revision",
        "base_model_sha256",
        "rules_sha256",
        "tools_sha256",
        "k",
        "hidden_size",
        "placeholder_id",
        "train_config_sha256",
        "dataset_sha256",
        "backend_id",
        "gist_sha256",
    }


@pytest.mark.parametrize("name", sorted(document()))
def test_a_missing_field_is_rejected(name: str) -> None:
    broken = document()
    del broken[name]
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(broken))


@pytest.mark.parametrize(
    ("name", "value"),
    [("k", 0), ("k", "16"), ("k", True), ("hidden_size", -1), ("run_id", ""), ("backend_id", 3)],
)
def test_a_field_of_the_wrong_type_or_range_is_rejected(name: str, value: object) -> None:
    broken = document()
    broken[name] = value
    with pytest.raises(ManifestError, match=name):
        parse_manifest(json.dumps(broken))


def test_unknown_fields_and_other_schemas_are_rejected() -> None:
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps({**document(), "extra": 1}))
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps({**document(), "schema": 2}))
    with pytest.raises(ManifestError):
        parse_manifest("[1]")
    with pytest.raises(ManifestError, match="not valid JSON"):
        parse_manifest("{nope")


def test_a_missing_manifest_file_is_a_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match=MANIFEST_FILE):
        read_manifest(tmp_path)


def test_sha256_of_a_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_base_model_identity_comes_from_revision_and_sums_files(tmp_path: Path) -> None:
    (tmp_path / ".revision").write_text("abc123\n")
    (tmp_path / "SHA256SUMS").write_text("sums")
    base = read_base_model(tmp_path)
    assert base.revision == "abc123"
    assert base.sha256 == sha256_file(tmp_path / "SHA256SUMS")


def test_base_model_without_revision_or_sums_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="download-models"):
        read_base_model(tmp_path)
    (tmp_path / ".revision").write_text("\n")
    (tmp_path / "SHA256SUMS").write_text("sums")
    with pytest.raises(ManifestError, match="empty"):
        read_base_model(tmp_path)
