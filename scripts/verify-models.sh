#!/usr/bin/env bash
set -euo pipefail
# shellcheck disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/models_lib.sh"
models_dir=${GISTING_MODELS_DIR:-$HOME/models/hf}

usage() {
  echo "usage: scripts/verify-models.sh [id ...]"
  echo "env: GISTING_MODELS_DIR (default \$HOME/models/hf), GISTING_CANDIDATES"
}

wanted=()
for arg in "$@"; do
  case $arg in
    -h | --help) usage; exit 0 ;;
    -*) usage >&2; die "unknown option $arg" ;;
    *) wanted+=("$arg") ;;
  esac
done

check_model() {
  local dir=$models_dir/$1 rev=$2
  [ -d "$dir" ] || { echo "missing directory $dir"; return 1; }
  [ -f "$dir/config.json" ] || { echo "config.json missing"; return 1; }
  [ -f "$dir/.revision" ] || { echo ".revision missing"; return 1; }
  [ "$(cat "$dir/.revision")" = "$rev" ] || { echo "revision mismatch: have $(cat "$dir/.revision"), want $rev"; return 1; }
  [ -s "$dir/SHA256SUMS" ] || { echo "SHA256SUMS missing or empty"; return 1; }
  find "$dir" -maxdepth 1 -name '*.safetensors' | grep -q . || { echo "no .safetensors file"; return 1; }
  (cd "$dir" && sha256_cmd -c SHA256SUMS >/dev/null 2>&1) || { echo "checksum mismatch"; return 1; }
  if [ -f "$dir/HUB_LFS_SHA256" ]; then
    (cd "$dir" && sha256_cmd -c HUB_LFS_SHA256 >/dev/null 2>&1) || { echo "hub lfs checksum mismatch"; return 1; }
  fi
  local shards
  shards=$(missing_shards "$dir") || { echo "unreadable model.safetensors.index.json"; return 1; }
  [ -z "$shards" ] || { echo "missing shards: $shards"; return 1; }
}

rows=$(select_rows ${wanted[@]+"${wanted[@]}"})
failed=0
while IFS=$'\t' read -r id _ rev _; do
  if reason=$(check_model "$id" "$rev"); then
    echo "OK   $id"
  else
    echo "FAIL $id: $reason"
    failed=1
  fi
done <<<"$rows"
exit "$failed"
