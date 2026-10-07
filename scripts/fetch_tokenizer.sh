#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$script_dir/models_lib.sh"
pin_file=${GISTING_TOKENIZER_PIN:-$root/data/eval/tokenizer-pin.json}
endpoint=${GISTING_HUB_ENDPOINT:-https://huggingface.co}
endpoint=${endpoint%/}
attempts=${GISTING_HUB_RETRIES:-5}
backoff=${GISTING_HUB_BACKOFF:-2}
attempt_limit=$((attempts < 1 ? 1 : attempts))

[ $# -eq 1 ] || die "usage: scripts/fetch_tokenizer.sh <dest-dir>"
dest=$1

read_pin() {
  python3 - "$pin_file" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1]) as handle:
        pin = json.load(handle)
    repo, revision, files = pin["repo"], pin["revision"], pin["files"]
except (OSError, ValueError, KeyError) as error:
    sys.exit(f"error: cannot read {sys.argv[1]}: {error}")
if not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
    sys.exit(f"error: revision must be a 40-hex commit sha, got {revision}")
if not files:
    sys.exit("error: pin lists no files")
for name, sha in files.items():
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name.startswith("."):
        sys.exit(f"error: unsafe file name {name}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
        sys.exit(f"error: bad sha256 for {name}")
    print(f"{repo}\t{revision}\t{name}\t{sha}")
PY
}

digest_of() {
  sha256_cmd "$1" | cut -d' ' -f1
}

fetch() {
  local url=$1 out=$2 attempt=0
  while ! curl -fsSL --max-time 120 -o "$out" "$url"; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt "$attempt_limit" ] || return 1
    sleep "$(awk -v b="$backoff" -v a="$((attempt - 1))" 'BEGIN { print b * 2 ^ a }')"
  done
}

rows=$(read_pin) || exit 1
mkdir -p "$dest"
part=
trap 'rm -f "$part"' EXIT
while IFS=$'\t' read -r repo revision name sha; do
  target=$dest/$name
  if [ -f "$target" ] && [ "$(digest_of "$target")" = "$sha" ]; then
    echo "ok $name (cached)" >&2
    continue
  fi
  part=$target.part
  fetch "$endpoint/$repo/resolve/$revision/$name" "$part" || die "cannot download $name from $endpoint after $attempt_limit attempts"
  got=$(digest_of "$part")
  if [ "$got" != "$sha" ]; then
    rm -f "$target"
    die "sha256 mismatch for $name: want $sha, got $got"
  fi
  mv "$part" "$target"
  part=
  echo "ok $name" >&2
done <<<"$rows"
