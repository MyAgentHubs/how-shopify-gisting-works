import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from guard_support import SigningKey, allow, git, make_key, sign, write

from gisting.eval.baseline import Baseline, Epoch, Mode
from gisting.eval.baseline_update import Candidate, dump_baseline
from gisting.eval.guard_git import GuardChange, staged_change, staged_genesis_change
from gisting.eval.guard_signature import signed_message
from gisting.eval.ratchet_audit import AuditResult, audit
from gisting.eval.registry import Metric
from gisting.eval.report import ReportError

BACKEND, RULES = "backend-one", "rules-one"
BASELINE = "eval/baseline.json"
N = 300
GOOD: dict[str, float] = {"red": 0.0, "rate": 0.2, "tokens": 100.0}
GUARD_PATTERNS = [
    "eval/genesis.json",
    "data/eval/guard.json",
    ".github/allowed_signers",
    "eval/baseline.json",
    "eval/metrics.toml",
    "scripts/check_eval_ratchet.py",
]
GATED_TEXT = (
    'stability_basis = "s"\nvalidated_against = "v"\nwhere_to_look = "w"\n'
    'journey = "J1"\ndirection = "down"\n'
)
METRICS_TOML = (
    f'[[metric]]\nname = "red"\ngate = "redline"\ntolerance = 0\nmin_cases = 100\n{GATED_TEXT}\n'
    f'[[metric]]\nname = "rate"\ngate = "ratchet"\ntolerance = 0\n{GATED_TEXT}\n'
    '[[metric]]\nname = "tokens"\ngate = "record"\ndirection = "down"\njourney = "J1"\n'
)
CASE_IDS = ("case_a", "case_b", "case_c")
CASES_FILE = "eval/cases/dev/family.jsonl"
CASES_TEXT = "".join(
    json.dumps({"id": case, "red_line": 1, "expect": {"scenario": "ask"}}) + "\n"
    for case in CASE_IDS
)
BASE_FILES = {
    CASES_FILE: CASES_TEXT,
    "data/eval/guard.json": json.dumps({"paths": GUARD_PATTERNS}),
    "eval/genesis.json": '{"version": 1}\n',
    "eval/metrics.toml": METRICS_TOML,
    "scripts/check_eval_ratchet.py": "pass\n",
    "README.md": "readme\n",
}


def tree_name(number: int) -> str:
    return f"{number:040x}"


def epoch(mode: Mode = "full", *, rules: str = RULES, **changes: float) -> Epoch:
    return Epoch(BACKEND, rules, mode, {**GOOD, **changes})


def baseline_text(*epochs: Epoch) -> str:
    return dump_baseline(Baseline(1, epochs or (epoch(),)))


def report_files(
    number: int,
    mode: Mode = "full",
    *,
    rules: str = RULES,
    identity_ok: bool = True,
    **changes: float,
) -> dict[str, str]:
    base = f"eval/reports/{tree_name(number)}/{mode}"
    document = {
        "run": {"backend_id": BACKEND, "rules_version": rules, "mode": mode},
        "n": N,
        "rates": {**GOOD, **changes},
        "identity_ok": identity_ok,
        "cases": {"splits": ["dev"]},
    }
    rows = "".join(json.dumps({"case_id": case}) + "\n" for case in CASE_IDS)
    return {f"{base}/report.json": json.dumps(document), f"{base}/transcripts.jsonl": rows}


def fake_loader(directory: Path, metrics: Sequence[Metric]) -> Candidate:
    document = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    if not document["identity_ok"]:
        message = "report identity differs"
        raise ReportError(message)
    run, rates = document["run"], cast(dict[str, float | None], document["rates"])
    flags = {
        item.name: {f"c{i}": i < round(value * N) for i in range(N)}
        for item in metrics
        if item.gate != "record" and (value := rates.get(item.name)) is not None
    }
    return Candidate(
        run["backend_id"], run["rules_version"], cast(Mode, run["mode"]), rates, flags, flags
    )


@dataclass
class Lab:
    root: Path
    key: SigningKey

    def head(self) -> str:
        return git(self.root, "rev-parse", "HEAD")

    def stage(self, files: Mapping[str, str | None]) -> None:
        for name, text in files.items():
            if text is None:
                git(self.root, "rm", "-q", "--", name)
            else:
                write(self.root, {name: text})
                git(self.root, "add", "--", name)

    def commit(self, files: Mapping[str, str | None], message: str = "step") -> str:
        self.stage(files)
        git(self.root, "commit", "-q", "--allow-empty", "-m", message)
        return self.head()

    def sign_staged(self, change: GuardChange, key: SigningKey | None = None) -> None:
        message = signed_message(change.parent_tree, change.digest)
        path = sign(self.root, key or self.key, change.digest, message)
        git(self.root, "add", "--", str(path.relative_to(self.root)))

    def signed_commit(
        self, files: Mapping[str, str | None], key: SigningKey | None = None, message: str = "step"
    ) -> str:
        self.stage(files)
        self.sign_staged(staged_change(self.root), key)
        git(self.root, "commit", "-q", "-m", message)
        return self.head()

    def genesis(
        self,
        files: Mapping[str, str | None] | None = None,
        *,
        signer: SigningKey | None = None,
        signed: bool = True,
        late: Mapping[str, str | None] | None = None,
    ) -> str:
        self.stage({"eval/baseline.json": baseline_text(), **BASE_FILES, **(files or {})})
        allow(self.root, self.key)
        git(self.root, "add", "--", ".github/allowed_signers")
        if signed:
            self.sign_staged(staged_genesis_change(self.root), signer)
        self.stage(late or {})
        git(self.root, "commit", "-q", "-m", "genesis")
        return self.head()


def new_lab(tmp_path: Path, *, with_history: bool = True) -> Lab:
    root = tmp_path / "lab"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    lab = Lab(root, make_key(tmp_path))
    if with_history:
        lab.commit({"before.txt": "history\n"}, "before the anchor")
    return lab


def other_key(tmp_path: Path, name: str = "other") -> SigningKey:
    return make_key(tmp_path, name)


def run(lab: Lab) -> AuditResult:
    return audit(lab.root, fake_loader)


def messages(result: AuditResult) -> str:
    return "\n".join(item.message for item in result.findings)


def culprits(result: AuditResult) -> set[str]:
    return {item.commit for item in result.findings}
