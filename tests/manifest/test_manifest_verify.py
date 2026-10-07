from dataclasses import replace
from pathlib import Path

import pytest
from manifest_support import artifact, expected_of

from gisting.manifest.record import GIST_FILE
from gisting.manifest.verify import ManifestMismatch, verify_manifest


def test_a_matching_artifact_verifies(tmp_path: Path) -> None:
    item = artifact(tmp_path)
    verify_manifest(tmp_path, item, expected_of(item))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("base_model_revision", "other"),
        ("base_model_sha256", "0" * 64),
        ("rules_sha256", "0" * 64),
        ("tools_sha256", "0" * 64),
        ("hidden_size", 64),
        ("placeholder_id", 701),
        ("backend_id", "transformers-mps-bfloat16"),
    ],
)
def test_every_runtime_difference_fails_fast_and_names_the_field(
    tmp_path: Path, name: str, value: str | int
) -> None:
    item = artifact(tmp_path)
    with pytest.raises(ManifestMismatch, match=name):
        verify_manifest(tmp_path, item, replace(expected_of(item), **{name: value}))


def test_a_changed_gist_file_fails_the_artifact_hash(tmp_path: Path) -> None:
    item = artifact(tmp_path)
    (tmp_path / GIST_FILE).write_bytes(b"tampered")
    with pytest.raises(ManifestMismatch, match="gist_sha256"):
        verify_manifest(tmp_path, item, expected_of(item))


def test_a_missing_gist_file_fails_fast(tmp_path: Path) -> None:
    item = artifact(tmp_path)
    (tmp_path / GIST_FILE).unlink()
    with pytest.raises(ManifestMismatch, match="missing"):
        verify_manifest(tmp_path, item, expected_of(item))


def test_all_differences_are_reported_together(tmp_path: Path) -> None:
    item = artifact(tmp_path)
    wrong = replace(expected_of(item), rules_sha256="0" * 64, backend_id="x")
    with pytest.raises(ManifestMismatch) as caught:
        verify_manifest(tmp_path, item, wrong)
    assert "rules_sha256" in str(caught.value)
    assert "backend_id" in str(caught.value)
