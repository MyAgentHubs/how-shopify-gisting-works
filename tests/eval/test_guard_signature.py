import hashlib
from pathlib import Path

import pytest
from guard_support import allow, make_key, sign

from gisting.eval.guard_signature import (
    EMPTY_TREE,
    File,
    Invalid,
    Missing,
    Valid,
    changed_paths,
    diff_hash,
    parse_patterns,
    protected_names,
    signed_message,
    verify,
)

PATTERNS = ("eval/baseline.json", "src/gisting/eval/baseline*.py", "scripts/check_eval_ratchet.py")
MODE = "100644"
PARENT = {"eval/baseline.json": File(MODE, b"old"), "README.md": File(MODE, b"readme")}
NEW = {"eval/baseline.json": File(MODE, b"new"), "README.md": File(MODE, b"readme changed")}
DIGEST = "d" * 64
TREE = "a" * 40


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def test_diff_hash_is_the_documented_record_stream() -> None:
    parent = {
        "eval/baseline.json": File(MODE, b"old"),
        "scripts/check_eval_ratchet.py": File(MODE, b"same"),
    }
    new = {
        "eval/baseline.json": File("100755", b"new"),
        "scripts/check_eval_ratchet.py": File(MODE, b"same"),
        "src/gisting/eval/baseline_diff.py": File("120000", b"added"),
    }
    first = ["eval/baseline.json", MODE, sha(b"old"), "100755", sha(b"new")]
    second = ["src/gisting/eval/baseline_diff.py", "absent", "absent", "120000", sha(b"added")]
    expected = sha("\0".join(first) + "\n" + "\0".join(second) + "\n")
    assert diff_hash(PATTERNS, parent, new) == expected
    assert changed_paths(PATTERNS, parent, new) == [
        "eval/baseline.json",
        "src/gisting/eval/baseline_diff.py",
    ]


def test_diff_hash_records_a_deleted_file_as_absent() -> None:
    old = {"eval/baseline.json": File(MODE, b"old")}
    expected = sha(f"eval/baseline.json\0{MODE}\0{sha(b'old')}\0absent\0absent\n")
    assert diff_hash(PATTERNS, old, {}) == expected
    assert diff_hash(PATTERNS, old, {"eval/baseline.json": None}) == expected


def test_a_mode_change_alone_changes_the_hash_and_the_changed_paths() -> None:
    plain = {"scripts/check_eval_ratchet.py": File(MODE, b"same")}
    executable = {"scripts/check_eval_ratchet.py": File("100755", b"same")}
    link = {"scripts/check_eval_ratchet.py": File("120000", b"same")}
    assert changed_paths(PATTERNS, plain, executable) == ["scripts/check_eval_ratchet.py"]
    assert changed_paths(PATTERNS, plain, plain) == []
    hashes = {diff_hash(PATTERNS, plain, executable), diff_hash(PATTERNS, plain, link)}
    assert len(hashes | {diff_hash(PATTERNS, executable, link)}) == 3
    assert diff_hash(PATTERNS, plain, plain) not in hashes


def test_diff_hash_ignores_input_order_and_unrelated_files() -> None:
    parent = {
        "eval/baseline.json": File(MODE, b"old"),
        "src/gisting/eval/baseline.py": File(MODE, b"a"),
    }
    new = {
        "eval/baseline.json": File(MODE, b"new"),
        "src/gisting/eval/baseline.py": File(MODE, b"b"),
    }
    noisy_new = {
        **new,
        "docs/readme.md": File(MODE, b"x"),
        "src/gisting/eval/report.py": File(MODE, b"y"),
    }
    reference = diff_hash(PATTERNS, parent, new)
    assert diff_hash(PATTERNS, dict(reversed(parent.items())), dict(reversed(new.items()))) == (
        reference
    )
    assert diff_hash(PATTERNS, parent, noisy_new) == reference
    assert diff_hash(tuple(reversed(PATTERNS)), parent, new) == reference


def test_diff_hash_ignores_protected_files_that_did_not_change() -> None:
    reference = diff_hash(PATTERNS, PARENT, NEW)
    same = {"scripts/check_eval_ratchet.py": File(MODE, b"same")}
    assert diff_hash(PATTERNS, {**PARENT, **same}, {**NEW, **same}) == reference


def test_diff_hash_changes_with_protected_content_on_either_side() -> None:
    reference = diff_hash(PATTERNS, PARENT, NEW)
    assert (
        diff_hash(PATTERNS, PARENT, {**NEW, "eval/baseline.json": File(MODE, b"neW")}) != reference
    )
    assert (
        diff_hash(PATTERNS, {**PARENT, "eval/baseline.json": File(MODE, b"olD")}, NEW) != reference
    )
    assert diff_hash(PATTERNS, PARENT, PARENT) == sha("")


def test_glob_star_stays_inside_one_directory() -> None:
    nested = {"src/gisting/eval/baseline/deep.py": File(MODE, b"x")}
    assert changed_paths(PATTERNS, {}, nested) == []
    deep = {"scripts/a/b/c.py": File(MODE, b"x")}
    assert changed_paths(("scripts/**/*.py",), {}, deep) == ["scripts/a/b/c.py"]
    flat = {"ab.txt": File(MODE, b"x"), "abc.txt": File(MODE, b"x")}
    assert changed_paths(("a?.txt",), {}, flat) == ["ab.txt"]


def test_signed_message_binds_the_version_the_parent_tree_and_the_hash() -> None:
    assert signed_message(TREE, "ab" * 32) == (
        b"gisting-eval-guard-v2\n" + TREE.encode() + b"\n" + b"ab" * 32 + b"\n"
    )
    assert signed_message(TREE, DIGEST) != signed_message(EMPTY_TREE, DIGEST)
    assert EMPTY_TREE == "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def test_parse_patterns_rejects_a_malformed_document() -> None:
    assert parse_patterns(b'{"paths": ["a", "b"]}') == ("a", "b")
    for bad in (b"{}", b'{"paths": []}', b'{"paths": [""]}', b'{"paths": [1]}', b"not json"):
        with pytest.raises(ValueError, match="guard"):
            parse_patterns(bad)


def test_the_shipped_guard_file_protects_itself_and_the_ratchet() -> None:
    shipped = Path(__file__).resolve().parents[2] / "data" / "eval" / "guard.json"
    patterns = parse_patterns(shipped.read_bytes())
    names = {
        "eval/baseline.json": True,
        "eval/metrics.toml": True,
        ".github/allowed_signers": True,
        ".github/workflows/ci.yml": True,
        ".github/eval-signatures/x.sig": False,
        "data/eval/guard.json": True,
        "src/gisting/eval/baseline.py": True,
        "src/gisting/eval/baseline_update.py": True,
        "src/gisting/eval/baseline_diff.py": True,
        "src/gisting/eval/ratchet.py": True,
        "src/gisting/eval/report_identity.py": True,
        "src/gisting/eval/guard_signature.py": True,
        "scripts/check_eval_ratchet.py": True,
        "src/gisting/eval/cli_baseline.py": True,
        "src/gisting/eval/report.py": True,
        "src/gisting/eval/report_tokens.py": True,
        "src/gisting/eval/registry.py": True,
        "src/gisting/eval/stats.py": True,
        "src/gisting/eval/ratchet_audit.py": True,
        "src/gisting/eval/ratchet_audit_reports.py": True,
        "src/gisting/eval/judging.py": False,
        "src/gisting/eval/applicability.py": False,
    }
    for name, expected in names.items():
        assert bool(protected_names(patterns, [name])) is expected, name


def test_verify_accepts_a_signature_by_the_allowed_signer(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    sign(tmp_path, key, DIGEST, signed_message(TREE, DIGEST))
    assert isinstance(verify(tmp_path, DIGEST, TREE), Valid)


def test_verify_rejects_a_signature_over_another_message(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    sign(tmp_path, key, DIGEST, signed_message(TREE, DIGEST) + b" ")
    result = verify(tmp_path, DIGEST, TREE)
    assert isinstance(result, Invalid)
    assert result.stderr


def test_verify_rejects_a_signature_made_for_another_digest(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    other = "e" * 64
    path = sign(tmp_path, key, other, signed_message(TREE, other))
    path.replace(path.with_name(f"{DIGEST}.sig"))
    assert isinstance(verify(tmp_path, DIGEST, TREE), Invalid)


def test_verify_rejects_a_signature_made_over_another_parent_tree(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    sign(tmp_path, key, DIGEST, signed_message(TREE, DIGEST))
    assert isinstance(verify(tmp_path, DIGEST, "b" * 40), Invalid)
    assert isinstance(verify(tmp_path, DIGEST, EMPTY_TREE), Invalid)


def test_verify_rejects_a_signature_made_for_the_old_message_version(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    sign(tmp_path, key, DIGEST, f"gisting-eval-guard-v1\n{DIGEST}\n".encode())
    assert isinstance(verify(tmp_path, DIGEST, TREE), Invalid)


@pytest.mark.parametrize("tree", ["", "HEAD", "../x", "A" * 40, "a" * 39])
def test_verify_refuses_a_malformed_parent_tree(tmp_path: Path, tree: str) -> None:
    result = verify(tmp_path, DIGEST, tree)
    assert isinstance(result, Invalid)
    assert "parent tree" in result.stderr


def test_verify_reports_a_missing_signature(tmp_path: Path) -> None:
    allow(tmp_path, make_key(tmp_path))
    assert isinstance(verify(tmp_path, DIGEST, TREE), Missing)


def test_verify_rejects_a_signature_in_the_wrong_namespace(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key)
    sign(tmp_path, key, DIGEST, signed_message(TREE, DIGEST), namespace="other-namespace")
    assert isinstance(verify(tmp_path, DIGEST, TREE), Invalid)


def test_verify_rejects_a_key_allowed_only_for_another_namespace(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key, namespace="other-namespace")
    sign(tmp_path, key, DIGEST, signed_message(TREE, DIGEST))
    assert isinstance(verify(tmp_path, DIGEST, TREE), Invalid)


def test_verify_rejects_a_key_allowed_under_another_identity(tmp_path: Path) -> None:
    key = make_key(tmp_path)
    allow(tmp_path, key, identity="someone-else")
    sign(tmp_path, key, DIGEST, signed_message(TREE, DIGEST))
    assert isinstance(verify(tmp_path, DIGEST, TREE), Invalid)


def test_verify_rejects_a_signature_by_an_unlisted_key(tmp_path: Path) -> None:
    allowed = make_key(tmp_path, "allowed")
    stranger = make_key(tmp_path, "stranger")
    allow(tmp_path, allowed)
    sign(tmp_path, stranger, DIGEST, signed_message(TREE, DIGEST))
    assert isinstance(verify(tmp_path, DIGEST, TREE), Invalid)


def test_verify_refuses_a_digest_that_could_leave_the_signature_directory(
    tmp_path: Path,
) -> None:
    result = verify(tmp_path, "../../etc/passwd", TREE)
    assert isinstance(result, Invalid)
    assert "digest" in result.stderr
