import pytest
from failure_support import IP, SESSION, Rig
from metering_support import CORRECT, World, service_for, wrong

from gisting.serve.contract import GenerateRequest
from gisting.serve.failures import FailureStats
from gisting.serve.service import Served

UNKNOWN_KEY = ("ip", "unknown")
MISSING = [None, ""]


def fail(rig: Rig, times: int, session: str, ip: str | None) -> None:
    view = rig.store.live(ip)
    for _ in range(times):
        view.record_failure(session)


@pytest.mark.parametrize("missing", MISSING)
def test_requests_without_an_ip_digest_fill_one_shared_bucket_that_locks_new_sessions(
    missing: str | None,
) -> None:
    rig = Rig().build(session=3, ip=5)
    for index in range(5):
        fail(rig, 1, f"session-{index}", missing)
    assert rig.store.count(UNKNOWN_KEY) == 5
    assert rig.store.live(missing).is_locked("fresh")
    assert rig.store.live(None).is_locked("another-fresh")


def test_none_and_the_empty_string_share_the_same_bucket() -> None:
    rig = Rig().build(session=3, ip=4)
    fail(rig, 2, "first", None)
    fail(rig, 2, "second", "")
    assert rig.store.count(UNKNOWN_KEY) == 4
    assert rig.store.live("").is_locked("third")


def test_the_unknown_bucket_never_locks_a_request_with_a_real_digest() -> None:
    rig = Rig().build(session=3, ip=5)
    for index in range(5):
        fail(rig, 1, f"session-{index}", None)
    assert rig.store.live(None).is_locked("fresh")
    assert not rig.store.live(IP).is_locked("fresh")
    assert rig.store.count(("ip", IP)) == 0


@pytest.mark.parametrize("missing", MISSING)
def test_a_missing_digest_still_locks_its_session_and_reports_once_per_view(
    missing: str | None,
) -> None:
    rig = Rig().build(session=3, ip=50)
    view = rig.store.live(missing)
    for _ in range(3):
        view.record_failure(SESSION)
        view.is_locked(SESSION)
        view.failures(SESSION)
    assert view.is_locked(SESSION)
    assert not rig.store.live(None).is_locked("other")
    assert rig.degraded == ["ip_digest_missing", "ip_digest_missing"]
    assert rig.store.stats() == FailureStats(evicted=0, ip_digest_missing=2)


def test_a_view_over_a_missing_digest_snapshots_and_spends_the_unknown_bucket() -> None:
    rig = Rig().build(session=9, ip=9)
    view = rig.store.live("")
    view.record_failure(SESSION)
    assert view.before().counts[UNKNOWN_KEY] == 0
    assert view.before().spent[UNKNOWN_KEY] == 1


def test_a_replay_without_a_digest_meters_against_the_unknown_bucket() -> None:
    rig = Rig().build(session=9, ip=2)
    replay = rig.store.replay(None, rig.store.live(None).before())
    for _ in range(2):
        replay.record_failure(SESSION)
    assert rig.store.count(UNKNOWN_KEY) == 2
    assert replay.is_locked("anyone")
    assert rig.degraded == []


@pytest.mark.parametrize("missing", MISSING)
def test_a_service_request_without_an_ip_digest_cannot_get_around_the_shared_ip_limit(
    missing: str | None,
) -> None:
    world = World()
    service = service_for(world, session=5, ip=20)
    for index in range(21):
        message = f"message {index}"
        world.plan[("gist", message)] = [wrong(f"w{index}")]
        request = GenerateRequest(f"session-{index:04d}", message, "gist")
        assert isinstance(service.handle(request, missing).result, Served)
    world.plan[("gist", "last")] = [CORRECT]
    request = GenerateRequest("session-last", "last", "gist")
    assert isinstance(service.handle(request, missing).result, Served)
    assert world.statuses("gist")[-2:] == ["locked", "locked"]
    assert service.failures.stats().ip_digest_missing == 22
