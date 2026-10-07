#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
verify=$here/../verify-models.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

rev=0123456789abcdef0123456789abcdef01234567
export GISTING_MODELS_DIR=$work/models
export GISTING_CANDIDATES=$work/candidates.json
mkdir -p "$GISTING_MODELS_DIR/tiny"
cat >"$GISTING_CANDIDATES" <<JSON
[{"id": "tiny", "repo": "x/tiny", "revision": "$rev", "license": "mit", "gated": false,
  "approx_size_gb": 0.0, "role": "main", "allow_patterns": ["*.json"]}]
JSON
model=$GISTING_MODELS_DIR/tiny
echo '{}' >"$model/config.json"
printf 'weights' >"$model/model.safetensors"
echo "$rev" >"$model/.revision"
(cd "$model" && shasum -a 256 config.json model.safetensors >SHA256SUMS)

expect() {
  local want=$1 label=$2 status=0
  "$verify" >"$work/out" 2>&1 || status=$?
  cat "$work/out"
  if { [ "$want" = ok ] && [ "$status" -ne 0 ]; } || { [ "$want" = fail ] && [ "$status" -eq 0 ]; }; then
    echo "TEST FAIL: $label (exit $status)" >&2
    exit 1
  fi
  echo "TEST PASS: $label"
}

expect ok "intact model passes"

printf 'tampered' >"$model/model.safetensors"
expect fail "tampered weights fail"
printf 'weights' >"$model/model.safetensors"
expect ok "restored weights pass"

echo "fedcba9876543210fedcba9876543210fedcba98" >"$model/.revision"
expect fail "wrong revision fails"
echo "$rev" >"$model/.revision"

rm "$model/config.json"
expect fail "missing config.json fails"
