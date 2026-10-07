import io
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fakes.model import FakeModel
from runner_support import GOOD_EMAIL, NUMBER, WRONG_EMAIL, lookup_call
from startup_support import (
    PATIENCE,
    Gauge,
    GaugedModel,
    Reply,
    Run,
    free_port,
    loaded_pair,
    lookup_parts,
    new_run,
    port_is_free,
    serve_environ,
)

from gisting.serve.__main__ import SIGNALS

ROOT = Path(__file__).resolve().parents[2]
SESSION = "session-aaaa1111"
OTHER_SESSION = "session-bbbb2222"
DIGEST = "ab" * 32
ASKING = f"Where is order #{NUMBER}? My email is {WRONG_EMAIL}"


def test_a_missing_ip_digest_is_logged_as_a_reason_code_and_nothing_else(tmp_path: Path) -> None:
    model = FakeModel([lookup_call(WRONG_EMAIL)] * 4 + ["Hello, how can I help?"] * 4)
    run = new_run(tmp_path).start(
        lambda _env: loaded_pair(model, FakeModel([])), lambda _env: lookup_parts()
    )
    run.wait_until_ready()
    run.generate(SESSION, ASKING, "gist")
    run.generate(OTHER_SESSION, ASKING, "gist", DIGEST)
    assert run.terminate() == 0
    degraded = [record for record in run.records() if record["event"] == "degraded"]
    assert degraded == [
        {"ts": degraded[0]["ts"], "event": "degraded", "fallback_reason": "ip_digest_missing"}
    ]
    output = run.stream.getvalue()
    for secret in (
        SESSION,
        OTHER_SESSION,
        DIGEST,
        run.environ["GISTING_UPSTREAM_SECRET"],
        GOOD_EMAIL,
    ):
        assert secret not in output


def test_mixed_gist_and_full_requests_never_run_two_turns_at_once(tmp_path: Path) -> None:
    gauge = Gauge()
    run = new_run(tmp_path).start(
        lambda _env: loaded_pair(GaugedModel(gauge), GaugedModel(gauge)),
        lambda _env: lookup_parts(),
    )
    run.wait_until_ready()
    for session in (SESSION, OTHER_SESSION):
        assert run.generate(session, "hello", "gist").status == 200
    jobs = [(SESSION, "full"), (OTHER_SESSION, "full"), ("session-cccc3333", "gist")]
    replies: list[Reply] = []

    def send(session: str, mode: str) -> None:
        replies.append(run.generate(session, "hello", mode))

    threads = [threading.Thread(target=send, args=job) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(PATIENCE)
    assert sorted(reply.status for reply in replies) == [200, 200, 200]
    assert gauge.peak == 1
    assert run.terminate() == 0


@pytest.mark.parametrize("number", SIGNALS)
def test_a_real_process_exits_zero_on_term_and_int_and_frees_the_port(
    tmp_path: Path, number: signal.Signals
) -> None:
    port = free_port()
    environ = {
        **serve_environ(tmp_path, port),
        "PYTHONPATH": str(ROOT / "tests"),
        "PATH": os.environ["PATH"],
    }
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "serve" / "serve_process.py")],
        env=environ,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        run = Run(port, io.StringIO(), environ)
        run.wait_until_ready()
        process.send_signal(number)
        assert process.wait(PATIENCE) == 0
        assert process.stderr is not None
        assert process.stderr.read() == ""
        assert port_is_free(port)
    finally:
        process.kill()
        process.wait()


def test_the_module_entry_point_refuses_an_empty_environment(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "gisting.serve"],
        env={"PATH": os.environ["PATH"]},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=PATIENCE,
        check=False,
    )
    assert done.returncode == 1
    assert done.stdout == ""
    assert "startup_failed" in done.stderr
    assert "GISTING_SERVE_PORT" in done.stderr
