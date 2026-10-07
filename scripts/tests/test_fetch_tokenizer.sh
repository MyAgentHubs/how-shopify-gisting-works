#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fetch=$here/../fetch_tokenizer.sh
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

fail() {
  echo "TEST FAIL: $1" >&2
  exit 1
}

rev=0123456789abcdef0123456789abcdef01234567
hub_files=$work/hub/x/tiny/resolve/$rev
mkdir -p "$hub_files"
printf '{"model": "tiny"}' >"$hub_files/tokenizer.json"
printf '{"chat_template": "t"}' >"$hub_files/tokenizer_config.json"
tok_sha=$(shasum -a 256 "$hub_files/tokenizer.json" | cut -d' ' -f1)
cfg_sha=$(shasum -a 256 "$hub_files/tokenizer_config.json" | cut -d' ' -f1)
export GISTING_TOKENIZER_PIN=$work/pin.json
cat >"$GISTING_TOKENIZER_PIN" <<JSON
{"repo": "x/tiny", "revision": "$rev",
 "files": {"tokenizer.json": "$tok_sha", "tokenizer_config.json": "$cfg_sha"}}
JSON

python3 -u -m http.server 0 --bind 127.0.0.1 --directory "$work/hub" >"$work/server.log" 2>&1 &
server_pid=$!
port=
for _ in $(seq 1 50); do
  port=$(sed -n 's/.*port \([0-9]*\).*/\1/p' "$work/server.log" | head -n1)
  [ -z "$port" ] || break
  sleep 0.1
done
[ -n "$port" ] || fail "fake hub did not start"
hub_endpoint=http://127.0.0.1:$port
export GISTING_HUB_ENDPOINT=$hub_endpoint
export GISTING_HUB_BACKOFF=0
export GISTING_HUB_RETRIES=3

run() {
  status=0
  "$fetch" "$@" >"$work/out" 2>&1 || status=$?
  cat "$work/out"
}

run "$work/dest"
[ "$status" -eq 0 ] || fail "clean fetch exits $status"
cmp -s "$work/dest/tokenizer.json" "$hub_files/tokenizer.json" || fail "tokenizer.json content"
cmp -s "$work/dest/tokenizer_config.json" "$hub_files/tokenizer_config.json" || fail "tokenizer_config.json content"
echo "TEST PASS: pinned files are downloaded and verified"

GISTING_HUB_ENDPOINT=http://127.0.0.1:1 run "$work/dest"
[ "$status" -eq 0 ] || fail "cached rerun exits $status"
grep -q 'tokenizer.json (cached)' "$work/out" || fail "cache hit not reported"
echo "TEST PASS: verified files are not downloaded again"

printf 'tampered' >"$work/dest/tokenizer.json"
run "$work/dest"
[ "$status" -eq 0 ] || fail "repair of a tampered file exits $status"
cmp -s "$work/dest/tokenizer.json" "$hub_files/tokenizer.json" || fail "tampered file not replaced"
echo "TEST PASS: a tampered local file is replaced"

printf 'poisoned' >"$hub_files/tokenizer.json"
rm -rf "$work/bad"
run "$work/bad"
[ "$status" -ne 0 ] || fail "hub serving different bytes must fail"
grep -q 'sha256 mismatch for tokenizer.json' "$work/out" || fail "mismatch message"
[ ! -e "$work/bad/tokenizer.json" ] || fail "mismatched file kept"
[ ! -e "$work/bad/tokenizer.json.part" ] || fail "partial file left behind"
printf '{"model": "tiny"}' >"$hub_files/tokenizer.json"
echo "TEST PASS: sha256 mismatch fails and keeps nothing"

run "$work/missing" extra
[ "$status" -ne 0 ] || fail "extra argument must fail"
status=0
"$fetch" >"$work/out" 2>&1 || status=$?
[ "$status" -ne 0 ] || fail "missing destination must fail"
grep -q 'usage' "$work/out" || fail "usage message"
echo "TEST PASS: destination argument is required"

sed "s/$rev/main/" "$work/pin.json" >"$work/pin-main.json"
GISTING_TOKENIZER_PIN=$work/pin-main.json run "$work/floating"
[ "$status" -ne 0 ] || fail "floating revision must fail"
grep -q '40-hex commit sha' "$work/out" || fail "revision message"
[ ! -e "$work/floating/tokenizer.json" ] || fail "downloaded despite a bad pin"
echo "TEST PASS: a pin that is not a commit sha is refused"

cat >"$work/flaky.py" <<'PY'
import http.server
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
  python3 -u "$work/flaky.py" "$1" "$2" >"$work/flaky.port" &
  flaky_pid=$!
  flaky_port=
  for _ in $(seq 1 50); do
    flaky_port=$(head -n1 "$work/flaky.port")
    [ -z "$flaky_port" ] || break
    sleep 0.1
  done
  [ -n "$flaky_port" ] || fail "flaky hub did not start"
}

printf '{"model": "solo"}' >"$work/solo.json"
solo_sha=$(shasum -a 256 "$work/solo.json" | cut -d' ' -f1)
cat >"$work/pin-solo.json" <<JSON
{"repo": "x/tiny", "revision": "$rev", "files": {"tokenizer.json": "$solo_sha"}}
JSON

start_flaky "$work/solo.json" 2
GISTING_TOKENIZER_PIN=$work/pin-solo.json GISTING_HUB_ENDPOINT=http://127.0.0.1:$flaky_port run "$work/flaky-dest"
[ "$status" -eq 0 ] || fail "retry after 2 transient failures exits $status"
cmp -s "$work/flaky-dest/tokenizer.json" "$work/solo.json" || fail "flaky content"
echo "TEST PASS: transient connection drop and 500 are retried"

start_flaky "$work/solo.json" 999
GISTING_TOKENIZER_PIN=$work/pin-solo.json GISTING_HUB_ENDPOINT=http://127.0.0.1:$flaky_port run "$work/down-dest"
[ "$status" -ne 0 ] || fail "persistent failure must exit non-zero"
grep -q 'cannot download tokenizer.json' "$work/out" || fail "download error message"
[ ! -e "$work/down-dest/tokenizer.json" ] || fail "file written on failure"
[ ! -e "$work/down-dest/tokenizer.json.part" ] || fail "partial file left on failure"
echo "TEST PASS: persistent network failure exits non-zero and leaves nothing"
