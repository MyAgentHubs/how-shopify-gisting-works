#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
check=$here/../hub_lfs_check.py
verify=$here/../verify-models.sh
download=$here/../download-models.sh
work=$(mktemp -d)
server_pid=
flaky_pid=
cleanup() {
  [ -z "$server_pid" ] || kill "$server_pid" 2>/dev/null || true
  [ -z "$server_pid" ] || wait "$server_pid" 2>/dev/null || true
  [ -z "$flaky_pid" ] || kill "$flaky_pid" 2>/dev/null || true
  [ -z "$flaky_pid" ] || wait "$flaky_pid" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT

rev=0123456789abcdef0123456789abcdef01234567
weights_sha=$(printf 'weights' | shasum -a 256 | cut -d' ' -f1)
api_dir=$work/hub/api/models/x/tiny/revision
mkdir -p "$api_dir" "$work/model"
cat >"$api_dir/$rev" <<JSON
{"siblings": [
  {"rfilename": "config.json"},
  {"rfilename": "model.safetensors", "lfs": {"sha256": "$weights_sha", "size": 7}},
  {"rfilename": "onnx/model.onnx", "lfs": {"sha256": "$weights_sha", "size": 7}}
]}
JSON

python3 -u -m http.server 0 --bind 127.0.0.1 --directory "$work/hub" >"$work/server.log" 2>&1 &
server_pid=$!
port=
for _ in $(seq 1 50); do
  port=$(sed -n 's/.*port \([0-9]*\).*/\1/p' "$work/server.log" | head -n1)
  [ -z "$port" ] || break
  sleep 0.1
done
[ -n "$port" ] || { echo "fake hub did not start" >&2; exit 1; }
export GISTING_HUB_ENDPOINT=http://127.0.0.1:$port

fail() {
  echo "TEST FAIL: $1" >&2
  exit 1
}

run_check() {
  status=0
  python3 "$check" x/tiny "$rev" "$work/model" '*.safetensors' '*.json' >"$work/out" 2>"$work/err" || status=$?
  cat "$work/out" "$work/err"
}

echo '{}' >"$work/model/config.json"
printf 'weights' >"$work/model/model.safetensors"
run_check
[ "$status" -eq 0 ] || fail "matching hash exits $status"
grep -q '"verified": \["model.safetensors"\]' "$work/out" || fail "verified list missing"
[ "$(cat "$work/model/HUB_LFS_SHA256")" = "$weights_sha  model.safetensors" ] || fail "HUB_LFS_SHA256 content"
echo "TEST PASS: matching hash passes and writes HUB_LFS_SHA256"

rm "$work/model/HUB_LFS_SHA256"
printf 'tampered' >"$work/model/model.safetensors"
run_check
[ "$status" -eq 1 ] || fail "mismatch exits $status"
grep -q '"mismatched": \["model.safetensors"\]' "$work/out" || fail "mismatched list missing"
[ ! -e "$work/model/HUB_LFS_SHA256" ] || fail "HUB_LFS_SHA256 written on failure"
echo "TEST PASS: mismatched hash fails"

rm "$work/model/model.safetensors"
run_check
[ "$status" -eq 1 ] || fail "missing file exits $status"
grep -q '"missing": \["model.safetensors"\]' "$work/out" || fail "missing list missing"
echo "TEST PASS: hub-listed file missing locally fails"

status=0
python3 "$check" x/nope "$rev" "$work/model" '*.json' >"$work/out" 2>"$work/err" || status=$?
[ "$status" -ne 0 ] || fail "unknown repo must fail"
grep -q 'cannot read hub metadata' "$work/err" || fail "hub error message"
echo "TEST PASS: unreachable metadata fails loudly"

cat >"$work/flaky.py" <<'PY'
import http.server
import os
import sys

failures = int(sys.argv[2])
seen = 0
body = open(sys.argv[1], "rb").read()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global seen
        seen += 1
        if seen <= failures:
            if seen % 2:
                self.connection.close()
                return
            self.send_error(500)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
PY

start_flaky() {
  [ -z "$flaky_pid" ] || { kill "$flaky_pid" 2>/dev/null || true; wait "$flaky_pid" 2>/dev/null || true; }
  python3 -u "$work/flaky.py" "$api_dir/$rev" "$1" >"$work/flaky.port" &
  flaky_pid=$!
  flaky_port=
  for _ in $(seq 1 50); do
    flaky_port=$(head -n1 "$work/flaky.port")
    [ -z "$flaky_port" ] || break
    sleep 0.1
  done
  [ -n "$flaky_port" ] || fail "flaky hub did not start"
}

hub_endpoint=$GISTING_HUB_ENDPOINT
export GISTING_HUB_BACKOFF=0
printf 'weights' >"$work/model/model.safetensors"

start_flaky 2
export GISTING_HUB_ENDPOINT=http://127.0.0.1:$flaky_port
run_check
[ "$status" -eq 0 ] || fail "retry after 2 transient failures exits $status"
grep -q '"reason": "ok"' "$work/out" || fail "reason ok missing"
echo "TEST PASS: transient connection drop and 500 are retried"

start_flaky 999
export GISTING_HUB_ENDPOINT=http://127.0.0.1:$flaky_port
export GISTING_HUB_RETRIES=3
run_check
[ "$status" -eq 2 ] || fail "persistent network failure exits $status"
grep -q '"reason": "hub_unreachable"' "$work/out" || fail "reason hub_unreachable missing"
unset GISTING_HUB_RETRIES
echo "TEST PASS: persistent network failure exits 2"

export GISTING_HUB_ENDPOINT=$hub_endpoint

export GISTING_MODELS_DIR=$work/models
export GISTING_CANDIDATES=$work/candidates.json
cat >"$GISTING_CANDIDATES" <<JSON
[{"id": "tiny", "repo": "x/tiny", "revision": "$rev", "license": "mit", "gated": false,
  "approx_size_gb": 0.0, "role": "main", "allow_patterns": ["*.safetensors", "*.json"]}]
JSON
mkdir -p "$work/bin"
cat >"$work/bin/hf" <<'SH'
#!/usr/bin/env bash
[ "$2" != --help ] || exit 0
dest=
while [ $# -gt 0 ]; do
  [ "$1" != --local-dir ] || dest=$2
  shift
done
mkdir -p "$dest"
echo '{}' >"$dest/config.json"
printf '%s' "$FAKE_WEIGHTS" >"$dest/model.safetensors"
SH
chmod +x "$work/bin/hf"

status=0
FAKE_WEIGHTS=corrupt PATH=$work/bin:$PATH "$download" >"$work/out" 2>&1 || status=$?
cat "$work/out"
[ "$status" -ne 0 ] || fail "download of corrupt file must fail"
[ ! -e "$GISTING_MODELS_DIR/tiny/.revision" ] || fail ".revision written after failed hub check"
[ ! -e "$GISTING_MODELS_DIR/tiny/SHA256SUMS" ] || fail "SHA256SUMS written after failed hub check"
echo "TEST PASS: download refuses to finish on hub hash mismatch"

FAKE_WEIGHTS=weights PATH=$work/bin:$PATH "$download" >"$work/out" 2>&1 || { cat "$work/out"; fail "clean download failed"; }
"$verify" || fail "verify after clean download"
echo "TEST PASS: clean download passes hub check and verify"

cat >"$GISTING_MODELS_DIR/tiny/model.safetensors.index.json" <<JSON
{"weight_map": {"a": "model.safetensors", "b": "model-00002-of-00002.safetensors"}}
JSON
status=0
"$verify" >"$work/out" 2>&1 || status=$?
cat "$work/out"
[ "$status" -ne 0 ] || fail "missing shard must fail verify"
grep -q 'model-00002-of-00002.safetensors' "$work/out" || fail "missing shard not named"
echo "TEST PASS: index referencing a missing shard fails verify"

rm "$GISTING_MODELS_DIR/tiny/model.safetensors.index.json"
printf 'tampered' >"$GISTING_MODELS_DIR/tiny/model.safetensors"
(cd "$GISTING_MODELS_DIR/tiny" && shasum -a 256 config.json model.safetensors >SHA256SUMS)
status=0
"$verify" >"$work/out" 2>&1 || status=$?
cat "$work/out"
[ "$status" -ne 0 ] || fail "hub sums must catch a consistently re-summed tamper"
grep -q 'hub lfs checksum mismatch' "$work/out" || fail "hub mismatch message"
echo "TEST PASS: HUB_LFS_SHA256 catches tamper even when SHA256SUMS was regenerated"

FAKE_WEIGHTS=weights PATH=$work/bin:$PATH "$download" >"$work/out" 2>&1 || fail "redownload for network tests failed"
rm "$GISTING_MODELS_DIR/tiny/.revision" "$GISTING_MODELS_DIR/tiny/SHA256SUMS"

start_flaky 999
export GISTING_HUB_RETRIES=2
status=0
GISTING_HUB_ENDPOINT=http://127.0.0.1:$flaky_port FAKE_WEIGHTS=weights PATH=$work/bin:$PATH "$download" >"$work/out" 2>&1 || status=$?
cat "$work/out"
[ "$status" -ne 0 ] || fail "network failure must exit non-zero"
grep -q 'network error while fetching Hub metadata; weights are kept' "$work/out" || fail "network message missing"
! grep -qi 'delete' "$work/out" || fail "network failure must not advise delete"
[ -f "$GISTING_MODELS_DIR/tiny/model.safetensors" ] || fail "weights removed"
echo "TEST PASS: network failure keeps weights and does not advise re-download"

printf 'corrupt' >"$GISTING_MODELS_DIR/tiny/model.safetensors"
status=0
FAKE_WEIGHTS=weights PATH=$work/bin:$PATH "$download" --check-only >"$work/out" 2>&1 || status=$?
cat "$work/out"
[ "$status" -ne 0 ] || fail "check-only on corrupt weights must fail"
grep -q 'delete' "$work/out" || fail "mismatch must advise delete"
echo "TEST PASS: hash mismatch still advises delete"

cat >"$work/bin/hf" <<'SH'
#!/usr/bin/env bash
[ "$2" != --help ] || exit 0
echo called >>"$HF_CALLS"
SH
export HF_CALLS=$work/hf_calls
printf 'weights' >"$GISTING_MODELS_DIR/tiny/model.safetensors"
PATH=$work/bin:$PATH "$download" --check-only >"$work/out" 2>&1 || { cat "$work/out"; fail "check-only on good weights failed"; }
[ ! -e "$HF_CALLS" ] || fail "check-only must not call hf"
[ "$(cat "$GISTING_MODELS_DIR/tiny/.revision")" = "$rev" ] || fail ".revision not written by check-only"
[ -s "$GISTING_MODELS_DIR/tiny/SHA256SUMS" ] || fail "SHA256SUMS not written by check-only"
"$verify" || fail "verify after check-only"
echo "TEST PASS: --check-only skips hf and writes .revision and SHA256SUMS"
