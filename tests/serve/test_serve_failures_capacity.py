from failure_support import IP, Rig

TTL = 100.0


def fail(rig: Rig, session: str, ip: str = IP) -> bool:
    return rig.store.record(session, ip)


def test_expired_keys_are_purged_before_eviction_so_they_hold_no_capacity() -> None:
    rig = Rig().build(session=3, ip=50, ttl=TTL, keys=2)
    fail(rig, "old-1")
    fail(rig, "old-2")
    rig.clock.advance(TTL)
    fail(rig, "new-1")
    fail(rig, "new-2")
    assert rig.store.stats().evicted == 0
    assert rig.degraded == []
    assert rig.store.count(("session", "new-1")) == 1
    assert rig.store.count(("session", "new-2")) == 1


def test_a_key_that_expired_a_moment_ago_is_not_counted_as_an_eviction_victim() -> None:
    rig = Rig().build(session=3, ip=50, ttl=TTL, keys=2)
    fail(rig, "old")
    rig.clock.advance(TTL - 1)
    fail(rig, "live-1")
    rig.clock.advance(1)
    fail(rig, "live-2")
    assert rig.store.stats().evicted == 0
    assert rig.store.count(("session", "live-1")) == 1
    assert rig.store.count(("session", "live-2")) == 1


def test_a_full_table_of_live_keys_still_evicts_and_counts() -> None:
    rig = Rig().build(session=3, ip=50, ttl=TTL, keys=2)
    for name in ("a", "b", "c"):
        fail(rig, name)
    assert rig.store.stats().evicted == 1
    assert rig.degraded == ["failure_store_evicted"]
    assert rig.store.count(("session", "a")) == 0


def test_the_store_itself_refuses_to_count_a_fresh_session_on_a_locked_ip() -> None:
    rig = Rig().build(session=3, ip=5)
    assert all([fail(rig, f"session-{index}") for index in range(5)])
    assert not fail(rig, "fresh")
    assert rig.store.count(("session", "fresh")) == 0
    assert rig.store.count(("ip", IP)) == 5


def test_the_store_itself_refuses_to_count_a_locked_session() -> None:
    rig = Rig().build(session=2, ip=50)
    assert [fail(rig, "only") for _ in range(3)] == [True, True, False]
    assert rig.store.count(("session", "only")) == 2
    assert rig.store.count(("ip", IP)) == 2


def test_a_quiet_period_read_drops_expired_keys_from_memory() -> None:
    rig = Rig().build(session=3, ip=50, ttl=TTL, keys=4)
    fail(rig, "old")
    rig.clock.advance(TTL)
    assert rig.store.count(("session", "old")) == 0
    tables = rig.store._tables  # pyright: ignore[reportPrivateUsage]
    assert all(not table for table in tables.values())
