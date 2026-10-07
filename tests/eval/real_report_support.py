import json
import shutil
from pathlib import Path

from audit_support import Lab
from guard_support import git

REPO = Path(__file__).resolve().parents[2]
REPORT_TREE = "ee6c5c626278120523b9af02255958c0c9f5048c"
REPORT = f"eval/reports/{REPORT_TREE}/full"


def seed_inputs(lab: Lab) -> None:
    shutil.rmtree(lab.root / "eval" / "cases")
    for name in ("eval/cases", "data/demo-orders"):
        shutil.copytree(REPO / name, lab.root / name)
    policy = lab.root / "prompts" / "agent_policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(REPO / "prompts" / "agent_policy.json", policy)
    git(lab.root, "add", "--all", "--", "eval/cases", "data/demo-orders", "prompts")


def real_baseline(**changes: float) -> str:
    document = json.loads((REPO / "eval" / "baseline.json").read_text(encoding="utf-8"))
    for item in document["epochs"]:
        if item["mode"] == "full":
            item["metrics"].update(changes)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def anchored_with_real_inputs(lab: Lab, **baseline: float) -> None:
    lab.genesis({
        "eval/baseline.json": real_baseline(**baseline),
        "eval/metrics.toml": (REPO / "eval" / "metrics.toml").read_text(encoding="utf-8"),
    })
    seed_inputs(lab)
    lab.commit({})


def stage_real_report(lab: Lab) -> list[str]:
    shutil.copytree(REPO / REPORT, lab.root / REPORT)
    git(lab.root, "add", "--", REPORT)
    return [f"{REPORT}/{path.name}" for path in sorted((REPO / REPORT).iterdir())]
