from failure_support import IP, SESSION, Rig
from metering_support import CORRECT, World, serve_once, service_for, wrong
from metering_support import IP as ATTACKER_IP


def failing_turns(world: World, mode: str, message: str, label: str, count: int) -> None:
    world.plan[(mode, message)] = [wrong(f"{label}{index}") for index in range(count)]


def test_a_compared_session_can_verify_at_most_twice_its_limit() -> None:
    world = World()
    service = service_for(world, session=5, ip=100)
    failing_turns(world, "gist", "m", "g", 5)
    failing_turns(world, "full", "m", "f", 5)
    serve_once(service, "session-twice001", "m", "gist")
    serve_once(service, "session-twice001", "m", "full")
    assert world.statuses("gist") == ["no_match"] * 5
    assert world.statuses("full") == ["no_match"] * 5
    assert service.failures.count(("session", "session-twice001")) == 5
    world.plan[("gist", "after")] = [CORRECT]
    serve_once(service, "session-twice001", "after", "gist")
    assert world.statuses("gist")[-1] == "locked"
    assert "found" not in world.statuses("gist") + world.statuses("full")


def test_compared_sessions_on_one_ip_can_verify_at_most_twice_the_ip_limit() -> None:
    world = World()
    service = service_for(world, session=5, ip=20)
    sessions = [f"session-ipbound{index}" for index in range(4)]
    for index, session in enumerate(sessions):
        failing_turns(world, "gist", f"m{index}", f"g{index}", 5)
        failing_turns(world, "full", f"m{index}", f"f{index}", 5)
        serve_once(service, session, f"m{index}", "gist")
    for index, session in enumerate(sessions):
        serve_once(service, session, f"m{index}", "full")
    assert world.statuses("gist") == ["no_match"] * 20
    assert world.statuses("full") == ["no_match"] * 20
    assert service.failures.count(("ip", ATTACKER_IP)) == 20
    world.plan[("gist", "after")] = [CORRECT]
    serve_once(service, "session-ipbound-fresh", "after", "gist")
    assert world.statuses("gist")[-1] == "locked"
    assert "found" not in world.statuses("gist") + world.statuses("full")


def test_a_replay_count_is_zero_not_negative_when_the_gist_keys_expired_before_compare() -> None:
    rig = Rig().build(session=5, ip=50, ttl=100.0, keys=10)
    live = rig.store.live(IP)
    live.record_failure(SESSION)
    live.record_failure(SESSION)
    rig.clock.advance(100.0)
    replay = rig.store.replay(IP, live.before())
    assert replay.failures(SESSION) == 0
    assert not replay.is_locked(SESSION)


def test_a_replay_count_is_zero_not_negative_when_the_gist_keys_were_evicted_before_compare() -> (
    None
):
    rig = Rig().build(session=5, ip=50, ttl=100.0, keys=1)
    live = rig.store.live(IP)
    live.record_failure(SESSION)
    live.record_failure(SESSION)
    rig.store.record("other-session", IP)
    assert rig.store.count(("session", SESSION)) == 0
    replay = rig.store.replay(IP, live.before())
    assert replay.failures(SESSION) == 0
