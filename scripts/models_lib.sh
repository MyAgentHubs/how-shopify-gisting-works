#!/usr/bin/env bash
set -f

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
candidates_file=${GISTING_CANDIDATES:-$root/models/candidates.json}

die() {
  echo "error: $*" >&2
  exit 1
}

sha256_cmd() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$@"
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$@"
  else
    die "need shasum or sha256sum"
  fi
}

select_rows() {
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
  python3 - "$candidates_file" "$@" <<'PY'
import json
import sys

path, wanted = sys.argv[1], sys.argv[2:]
try:
    with open(path) as handle:
        rows = json.load(handle)
except (OSError, ValueError) as error:
    sys.exit(f"error: cannot read {path}: {error}")
known = [row["id"] for row in rows]
unknown = [name for name in wanted if name not in known]
if unknown:
    sys.exit(f"error: unknown id(s): {' '.join(unknown)}; known: {' '.join(known)}")
for row in rows:
    if wanted and row["id"] not in wanted:
        continue
    fields = [
        row["id"],
        row["repo"],
        row["revision"],
        str(row["gated"]).lower(),
        str(row["approx_size_gb"]),
        " ".join(row["allow_patterns"]),
    ]
    print("\t".join(fields))
PY
}

missing_shards() {
  python3 - "$1" <<'PY'
import json
import os
import sys

directory = sys.argv[1]
index = os.path.join(directory, "model.safetensors.index.json")
if not os.path.isfile(index):
    sys.exit(0)
try:
    with open(index) as handle:
        shards = set(json.load(handle)["weight_map"].values())
except (OSError, ValueError, KeyError, AttributeError) as error:
    sys.exit(f"cannot parse {index}: {error}")
missing = sorted(name for name in shards if not os.path.isfile(os.path.join(directory, name)))
if missing:
    print(" ".join(missing))
PY
}
