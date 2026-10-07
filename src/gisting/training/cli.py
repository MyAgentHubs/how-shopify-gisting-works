import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from gisting.eval.case import DECISION, FINAL, RAW
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.training.dataset import build_dataset
from gisting.training.errors import UsageError
from gisting.training.files import DEFAULT_ARTIFACTS
from gisting.training.samples import Sample, dump_jsonl, read_jsonl, sample_from_json, sample_json

USAGE_EXIT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gisting.training")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write the dataset as JSONL")
    build.add_argument("--out", type=Path, help="default: stdout")
    teach = commands.add_parser("teach", help="record the Full-rules teacher on every sample")
    teach.add_argument("--dataset", type=Path, help="default: stdin")
    teach.add_argument("--out", type=Path, required=True, help="teacher JSONL, resumable")
    teach.add_argument("--limit", type=int)
    keep = commands.add_parser("filter", help="keep only the teacher rows the grader passes")
    keep.add_argument("--teacher", type=Path, required=True)
    keep.add_argument("--out", type=Path, required=True, help="filtered teacher JSONL")
    keep.add_argument(
        "--layer",
        choices=(DECISION, RAW, FINAL),
        default=DECISION,
        help="decision: judge and facts only; raw: also the wording; final: exact sentences",
    )
    gist = commands.add_parser("gist", help="train the Gist vectors against the recorded teacher")
    gist.add_argument("--teacher", type=Path, required=True)
    gist.add_argument("--run-id", required=True)
    gist.add_argument("--out-dir", type=Path, default=DEFAULT_ARTIFACTS)
    compare = commands.add_parser("compare", help="Full vs untrained vs trained Gist on dev")
    compare.add_argument("--teacher", type=Path, required=True)
    compare.add_argument("--gist-dir", type=Path, required=True)
    compare.add_argument("--out", type=Path, help="default: <gist-dir>/report.json")
    return parser


def run_build(args: argparse.Namespace) -> int:
    text = dump_jsonl(sample_json(sample) for sample in build_dataset())
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


def read_dataset(path: Path | None) -> list[Sample]:
    lines = sys.stdin.read().splitlines() if path is None else path.read_text().splitlines()
    rows: list[Json] = [json.loads(line) for line in lines if line.strip()]
    return [sample_from_json(row) for row in rows if isinstance(row, dict)]


def run_teach(args: argparse.Namespace) -> int:
    from gisting.training.kit import make_kit
    from gisting.training.loading import load_runtime
    from gisting.training.teacher import teach

    _, model, tokenizer = load_runtime()
    samples = read_dataset(args.dataset)[: args.limit]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = teach(model, make_kit(tokenizer), samples, args.out)
    summary: JsonObject = {"taught": written, "teacher_file": str(args.out)}
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


def run_filter(args: argparse.Namespace) -> int:
    from gisting.eval.data import load_grader_data
    from gisting.training.filtering import filter_rows, summary_json

    filtered = filter_rows(read_jsonl(args.teacher), load_grader_data(), args.layer)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump_jsonl(filtered.kept_rows), encoding="utf-8")
    sys.stdout.write(json.dumps(summary_json(filtered)) + "\n")
    return 0


def run_gist(args: argparse.Namespace) -> int:
    from gisting.training.gist_run import Plan, run_training
    from gisting.training.hparams import load_hparams
    from gisting.training.loading import load_runtime

    config, model, tokenizer = load_runtime()
    plan = Plan(args.run_id, config, args.teacher, args.out_dir / args.run_id, load_hparams())
    sys.stdout.write(json.dumps(run_training(plan, model, tokenizer)) + "\n")
    return 0


def run_compare_command(args: argparse.Namespace) -> int:
    from gisting.training.compare_run import run_compare

    summary = run_compare(args.teacher, args.gist_dir, args.out or args.gist_dir / "report.json")
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        return {
            "build": run_build,
            "teach": run_teach,
            "filter": run_filter,
            "gist": run_gist,
            "compare": run_compare_command,
        }[args.command](args)
    except UsageError as error:
        sys.stderr.write(f"gisting.training: {error}\n")
        return USAGE_EXIT
