import sys
from pathlib import Path

from gisting.shopify.jsonvalue import JsonObject
from gisting.training.compare import (
    MODES,
    CompareMismatch,
    Subject,
    check_provenance,
    run_mode,
    teacher_outcomes,
)
from gisting.training.errors import UsageError
from gisting.training.hparams import load_hparams
from gisting.training.kit import make_kit
from gisting.training.loading import load_runtime
from gisting.training.report import build_report, write_outputs
from gisting.training.teacher import read_teacher


def run_compare(teacher_file: Path, gist_dir: Path, out: Path) -> JsonObject:
    _, model, tokenizer = load_runtime(gist_dir)
    manifest, injection = model.gist_manifest, model.gist
    if manifest is None or injection is None:
        message = f"no Gist artifact was loaded from {gist_dir}"
        raise UsageError(message)
    try:
        check_provenance(manifest, teacher_file)
    except CompareMismatch as error:
        raise UsageError(str(error)) from error
    kit = make_kit(tokenizer, manifest.k)
    subject = Subject(model, kit, manifest, load_hparams(), injection)
    records = [r for r in read_teacher(teacher_file) if r.sample.split == "dev"]
    modes = {}
    for mode in MODES:
        sys.stderr.write(f"gisting.training: compare mode {mode} on {len(records)} dev samples\n")
        modes[mode] = run_mode(subject, records, mode)
    report = build_report(subject, records, teacher_outcomes(records, kit), modes, gist_dir)
    write_outputs(report, gist_dir, out)
    return {"report": str(out), "run_id": manifest.run_id, "dev_samples": len(records)}
