from failure_support import IP, SESSION, Rig

from gisting.serve.config import LIMITS
from gisting.serve.failures import FailureLimits, FailureSnapshot, FailureStats
from gisting.tools.policy import load_policy

SESSION_KEY = ("session", SESSION)
IP_KEY = ("ip", IP)


def fail(rig: Rig, times: int, session: str = SESSION, ip: str | None = IP) -> None:
    view = rig.store.live(ip)
    for _ in range(times):
        view.record_failure(session)


def test_limits_come_from_the_data_file_and_the_lookup_policy() -> None:
    policy = load_policy()
    limits = FailureLimits.from_limits(LIMITS, policy.failure_limit)
    assert limits == FailureLimits(
        policy.failure_limit, LIMITS.ip_failure_limit, LIMITS.failure_ttl_s, LIMITS.max_failure_keys
    )
    assert (LIMITS.ip_failure_limit, LIMITS.failure_ttl_s, LIMITS.max_failure_keys) == (
        20,
        86400.0,
        10000,
    )
    assert LIMITS.ip_failure_limit > policy.failure_limit


def test_a_session_at_its_limit_is_locked() -> None:
    rig = Rig().build(session=3)
    fail(rig, 2)
    assert not rig.store.live(IP).is_locked(SESSION)
    fail(rig, 1)
    assert rig.store.live(IP).is_locked(SESSION)
    assert rig.store.live(IP).failures(SESSION) == 3


def test_an_ip_at_its_limit_locks_a_session_below_its_own_limit() -> None:
    rig = Rig().build(session=3, ip=5)
    for index in range(5):
        fail(rig, 1, session=f"session-{index}")
    fresh = rig.store.live(IP)
    assert fresh.failures("fresh") == 0
    assert fresh.is_locked("fresh")
    assert not rig.store.live("other-ip").is_locked("fresh")


def test_below_both_limits_nothing_is_locked() -> None:
    rig = Rig().build(session=3, ip=5)
    fail(rig, 2)
    fail(rig, 2, session="session-2")
    view = rig.store.live(IP)
    assert not view.is_locked(SESSION)
    assert not view.is_locked("session-2")
    assert not view.is_locked("session-3")


def test_the_lock_holds_to_the_ttl_and_releases_at_it() -> None:
    rig = Rig().build(session=3, ttl=86400.0)
    fail(rig, 3)
    rig.clock.advance(86400.0 - 0.001)
    assert rig.store.live(IP).is_locked(SESSION)
    rig.clock.advance(0.001)
    view = rig.store.live(IP)
    assert not view.is_locked(SESSION)
    assert view.failures(SESSION) == 0


def test_calls_refused_while_locked_do_not_extend_the_ttl() -> None:
    rig = Rig().build(session=3, ttl=100.0)
    fail(rig, 3)
    rig.clock.advance(60)
    fail(rig, 5)
    assert rig.store.live(IP).failures(SESSION) == 3
    rig.clock.advance(40)
    assert not rig.store.live(IP).is_locked(SESSION)


def test_the_ttl_slides_with_the_last_failure() -> None:
    rig = Rig().build(session=3, ttl=100.0)
    fail(rig, 1)
    rig.clock.advance(60)
    fail(rig, 1)
    rig.clock.advance(60)
    assert rig.store.live(IP).failures(SESSION) == 2
    rig.clock.advance(40)
    assert rig.store.live(IP).failures(SESSION) == 0


def test_a_full_store_evicts_the_oldest_key_counts_it_and_reports_it() -> None:
    rig = Rig().build(session=3, ip=50, keys=2)
    fail(rig, 2, session="first", ip=None)
    fail(rig, 1, session="second", ip=None)
    assert rig.store.stats().evicted == 0
    fail(rig, 1, session="third", ip=None)
    assert rig.store.stats().evicted == 1
    assert rig.degraded.count("failure_store_evicted") == 1
    view = rig.store.live(None)
    assert view.failures("first") == 0
    assert (view.failures("second"), view.failures("third")) == (1, 1)


def test_a_write_refreshes_a_keys_place_in_the_eviction_order() -> None:
    rig = Rig().build(session=9, keys=2)
    fail(rig, 1, session="first", ip=None)
    fail(rig, 1, session="second", ip=None)
    fail(rig, 1, session="first", ip=None)
    fail(rig, 1, session="third", ip=None)
    view = rig.store.live(None)
    assert (view.failures("first"), view.failures("second")) == (2, 0)


def test_a_session_key_flood_does_not_evict_ip_keys() -> None:
    rig = Rig().build(session=3, ip=10, keys=3)
    for index in range(10):
        fail(rig, 1, session=f"flood-{index}")
    assert rig.store.stats().evicted == 7
    assert rig.store.live(IP).is_locked("fresh")


def test_a_present_ip_digest_never_reports_the_degraded_mode() -> None:
    rig = Rig().build()
    fail(rig, 2)
    assert rig.degraded == []
    assert rig.store.stats() == FailureStats(evicted=0, ip_digest_missing=0)


def test_record_failure_counts_both_the_session_key_and_the_ip_key() -> None:
    rig = Rig().build(session=9, ip=9)
    fail(rig, 2)
    view = rig.store.live(IP)
    view.failures(SESSION)
    assert view.before() == FailureSnapshot({SESSION_KEY: 2, IP_KEY: 2})


def test_before_holds_each_keys_first_touch_value_and_what_the_view_itself_spent() -> None:
    rig = Rig().build(session=9, ip=9)
    fail(rig, 1)
    view = rig.store.live(IP)
    assert view.failures(SESSION) == 1
    view.record_failure(SESSION)
    view.record_failure(SESSION)
    view.is_locked("late-session")
    assert view.before() == FailureSnapshot(
        {SESSION_KEY: 1, IP_KEY: 1, ("session", "late-session"): 0},
        {SESSION_KEY: 2, IP_KEY: 2},
    )
    assert rig.store.live(IP).failures(SESSION) == 3


def test_a_failure_refused_because_the_key_is_locked_is_not_spent() -> None:
    rig = Rig().build(session=2, ip=9)
    view = rig.store.live(IP)
    for _ in range(5):
        view.record_failure(SESSION)
    assert view.before().spent == {SESSION_KEY: 2, IP_KEY: 2}
    assert rig.store.live(IP).failures(SESSION) == 2


def test_before_on_an_untouched_view_is_empty() -> None:
    assert Rig().build().store.live(IP).before() == FailureSnapshot({})


def spent(rig: Rig, times: int) -> FailureSnapshot:
    gist = rig.store.live(IP)
    for _ in range(times):
        gist.record_failure(SESSION)
    return gist.before()


def test_replay_writes_only_the_failures_beyond_what_the_gist_turn_spent() -> None:
    rig = Rig().build(session=9, ip=9)
    replay = rig.store.replay(IP, spent(rig, 1))
    replay.record_failure(SESSION)
    assert rig.store.live(IP).failures(SESSION) == 1
    for _ in range(3):
        replay.record_failure(SESSION)
    for _ in range(4):
        replay.record_failure("brand-new")
    live = rig.store.live(IP)
    assert (live.failures(SESSION), live.failures("brand-new")) == (4, 4)
    assert live.before().counts[IP_KEY] == 8
    assert replay.failures(SESSION) == 4
    assert rig.store.stats() == FailureStats(evicted=0, ip_digest_missing=0)


def test_replay_sees_failures_others_added_since_the_gist_turn_and_locks_earlier() -> None:
    rig = Rig().build(session=3, ip=9)
    snapshot = spent(rig, 1)
    fail(rig, 2)
    replay = rig.store.replay(IP, snapshot)
    assert replay.failures(SESSION) == 2
    assert not replay.is_locked(SESSION)
    replay.record_failure(SESSION)
    assert replay.failures(SESSION) == 3
    assert replay.is_locked(SESSION)
    assert rig.store.live(IP).failures(SESSION) == 3


def test_replay_reads_live_values_for_keys_the_snapshot_never_touched() -> None:
    rig = Rig().build(session=3, ip=9)
    fail(rig, 3, session="elsewhere")
    replay = rig.store.replay(IP, FailureSnapshot({}))
    assert replay.failures("elsewhere") == 3
    assert replay.is_locked("elsewhere")
    assert replay.failures(SESSION) == 0


def test_replay_overlay_locks_on_the_second_failure_like_the_live_view_does() -> None:
    live_rig, replay_rig = Rig().build(session=2, ip=9), Rig().build(session=2, ip=9)
    live = live_rig.store.live(IP)
    replay = replay_rig.store.replay(IP, FailureSnapshot({}))
    for view in (live, replay):
        assert not view.is_locked(SESSION)
        view.record_failure(SESSION)
        assert not view.is_locked(SESSION)
        view.record_failure(SESSION)
        assert view.is_locked(SESSION)
        view.record_failure(SESSION)
        assert view.failures(SESSION) == 2


def test_replay_locks_on_the_ip_limit_once_failures_beyond_the_gist_spend_reach_it() -> None:
    rig = Rig().build(session=9, ip=2)
    replay = rig.store.replay(IP, spent(rig, 1))
    replay.record_failure(SESSION)
    assert not replay.is_locked("b")
    replay.record_failure(SESSION)
    assert replay.is_locked("b")
    assert rig.store.live(IP).is_locked("b")


def test_a_replay_without_an_ip_digest_does_not_report_the_degraded_mode_again() -> None:
    rig = Rig().build()
    replay = rig.store.replay(None, FailureSnapshot({}))
    replay.is_locked(SESSION)
    replay.record_failure(SESSION)
    assert rig.degraded == []
    assert rig.store.stats() == FailureStats(evicted=0, ip_digest_missing=0)
