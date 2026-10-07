import tempfile
from pathlib import Path

from gisting.eval.guard_git import GuardChange
from gisting.eval.guard_signature import ALLOWED_SIGNERS, SIGNATURE_DIR, Invalid, Valid, verify
from gisting.eval.ratchet_audit_tree import Tree


def place(base: Path, name: str, content: bytes) -> None:
    target = base / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def signature_problem(signers: Tree, signed: Tree, change: GuardChange) -> str | None:
    keys = signers.read(ALLOWED_SIGNERS)
    if keys is None:
        return f"the revision that names the signers has no {ALLOWED_SIGNERS}"
    name = f"{SIGNATURE_DIR}/{change.digest}.sig"
    signature = signed.read(name)
    if signature is None:
        return f"no signature file {name} in the commit"
    with tempfile.TemporaryDirectory(prefix="gisting-audit-") as scratch:
        base = Path(scratch)
        place(base, ALLOWED_SIGNERS, keys)
        place(base, name, signature)
        result = verify(base, change.digest, change.parent_tree)
    if isinstance(result, Valid):
        return None
    detail = result.stderr if isinstance(result, Invalid) else "missing"
    return f"{name} is not a valid signature of an allowed signer: {detail}"
