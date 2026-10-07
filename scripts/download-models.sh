#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "$script_dir/models_lib.sh"
models_dir=${GISTING_MODELS_DIR:-$HOME/models/hf}

usage() {
  echo "usage: scripts/download-models.sh [--dry-run] [--check-only] [id ...]"
  echo "env: GISTING_MODELS_DIR (default \$HOME/models/hf), GISTING_CANDIDATES, GISTING_ALLOW_PATTERNS_OVERRIDE (test only)"
}

dry_run=0
check_only=0
wanted=()
for arg in "$@"; do
  case $arg in
    --dry-run) dry_run=1 ;;
    --check-only) check_only=1 ;;
    -h | --help) usage; exit 0 ;;
    -*) usage >&2; die "unknown option $arg" ;;
    *) wanted+=("$arg") ;;
  esac
done

require_hf() {
  command -v hf >/dev/null 2>&1 || die 'hf CLI not found; run: python3 -m pip install -U "huggingface_hub[cli]"'
  hf download --help >/dev/null 2>&1 || die 'hf CLI too old (need huggingface_hub >= 0.34); run: python3 -m pip install -U "huggingface_hub[cli]"'
}

write_sums() {
  (
    cd "$1"
    # shellcheck disable=SC2094
    find . -type f ! -path './.cache/*' ! -name SHA256SUMS ! -name .revision ! -name HUB_LFS_SHA256 -print0 |
      LC_ALL=C sort -z |
      while IFS= read -r -d '' file; do sha256_cmd "${file#./}"; done >SHA256SUMS
  )
}

check_hub() {
  local id=$1 repo=$2 rev=$3 dest=$4 patterns=$5
  local result pattern_args
  read -ra pattern_args <<<"$patterns"
  local status=0
  result=$(python3 "$script_dir/hub_lfs_check.py" "$repo" "$rev" "$dest" "${pattern_args[@]}") || status=$?
  case $status in
    0) ;;
    2)
      echo "$result" >&2
      die "$id: network error while fetching Hub metadata; weights are kept. Re-run the same command to retry the check (completed files are not re-downloaded), or use --check-only"
      ;;
    *)
      echo "$result" >&2
      die "$id failed the Hub LFS sha256 check; delete $dest and re-run"
      ;;
  esac
}

download_one() {
  local id=$1 repo=$2 rev=$3 gated=$4 dest=$models_dir/$1
  local patterns=${GISTING_ALLOW_PATTERNS_OVERRIDE:-$5}
  local include=() pattern
  for pattern in $patterns; do
    include+=(--include "$pattern")
  done
  if [ "$gated" = true ]; then
    echo "$id is gated: accept the terms at https://huggingface.co/$repo and run 'hf auth login' first" >&2
  fi
  local cmd=(hf download "$repo" --revision "$rev" --local-dir "$dest" "${include[@]}")
  if [ "$dry_run" = 1 ]; then
    printf '%q ' "${cmd[@]}"
    echo
    return
  fi
  if [ "$check_only" = 1 ]; then
    [ -d "$dest" ] || die "$id: $dest does not exist; nothing to check"
    echo "checking $id ($repo@${rev:0:8})" >&2
  else
    mkdir -p "$dest"
    echo "downloading $id ($repo@${rev:0:8})" >&2
    "${cmd[@]}" </dev/null >&2
  fi
  check_hub "$id" "$repo" "$rev" "$dest" "$patterns"
  echo "$rev" >"$dest/.revision"
  write_sums "$dest"
}

rows=$(select_rows ${wanted[@]+"${wanted[@]}"})
[ "$dry_run" = 1 ] || [ "$check_only" = 1 ] || require_hf

while IFS=$'\t' read -r id repo rev gated _ patterns; do
  download_one "$id" "$repo" "$rev" "$gated" "$patterns"
done <<<"$rows"

[ "$dry_run" = 1 ] && exit 0

while IFS=$'\t' read -r id _; do
  printf '%s\t%s\n' "$models_dir/$id" "$(du -sh "$models_dir/$id" | cut -f1)"
done <<<"$rows"
echo "copy to the target host (not run automatically):" >&2
echo "  rsync -avh --progress $models_dir/ <user>@<target-host>:~/models/hf/" >&2
echo "  or copy $models_dir/ to an external drive" >&2
echo "then run scripts/verify-models.sh there" >&2
