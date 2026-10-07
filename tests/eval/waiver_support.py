from collections.abc import Mapping, Sequence

from audit_support import Lab
from guard_support import SigningKey, git

from gisting.eval.guard_git import GuardChange, change_between, index_snapshot, tree_snapshot


def waiver_change(lab: Lab, files: Mapping[str, str | None], extra: Sequence[str]) -> GuardChange:
    lab.stage(files)
    return change_between(
        lab.root, tree_snapshot(lab.root, "HEAD"), index_snapshot(lab.root), tuple(extra)
    )


def waiver_commit(
    lab: Lab,
    files: Mapping[str, str | None],
    extra: Sequence[str],
    key: SigningKey | None = None,
    message: str = "waiver",
) -> str:
    lab.sign_staged(waiver_change(lab, files, extra), key)
    git(lab.root, "commit", "-q", "-m", message)
    return lab.head()
