from metering_support import CORRECT, IP, World, serve_once, service_for, wrong


def test_compare_lookups_beyond_an_idle_gist_turn_fill_the_shared_ip_count_up_to_its_limit() -> (
    None
):
    world = World()
    service = service_for(world, session=5, ip=20)
    for index in range(100):
        session, message = f"attacker-{index:04d}", f"message {index}"
        world.plan[("full", message)] = [wrong(f"a{index}"), wrong(f"b{index}")]
        serve_once(service, session, message, "gist")
        serve_once(service, session, message, "full")
    full = world.statuses("full")
    assert service.failures.count(("ip", IP)) == 20
    assert full.count("no_match") == 20
    assert full.count("locked") == 180
    assert "found" not in full


def test_a_compare_on_an_ip_locked_since_the_gist_turn_ends_locked_and_reveals_no_order() -> None:
    world = World()
    service = service_for(world, session=5, ip=20)
    message = "order 1042 please"
    world.plan[("gist", message)] = [wrong("w")]
    world.plan[("full", message)] = [wrong("w"), CORRECT]
    serve_once(service, "session-victim1", message, "gist")
    for index in range(19):
        burn = f"burn {index}"
        world.plan[("gist", burn)] = [wrong(f"b{index}")]
        serve_once(service, f"burner-{index:04d}", burn, "gist")
    assert service.failures.count(("ip", IP)) == 20
    serve_once(service, "session-victim1", message, "full")
    assert world.statuses("full") == ["no_match", "locked"]
    assert service.failures.count(("ip", IP)) == 20


def test_a_full_turn_that_repeats_the_gist_turns_failures_adds_nothing_and_agrees() -> None:
    world = World()
    service = service_for(world, session=5, ip=20)
    world.plan[("gist", "m")] = [wrong("g1"), wrong("g2")]
    world.plan[("full", "m")] = [wrong("g1"), wrong("g2")]
    serve_once(service, "session-bbbb2222", "m", "gist")
    serve_once(service, "session-bbbb2222", "m", "full")
    assert world.statuses("full") == world.statuses("gist") == ["no_match", "no_match"]
    assert service.failures.count(("session", "session-bbbb2222")) == 2
    assert service.failures.count(("ip", IP)) == 2


def test_a_full_turn_that_fails_more_than_the_gist_turn_has_only_the_excess_counted() -> None:
    world = World()
    service = service_for(world, session=5, ip=20)
    world.plan[("gist", "m")] = [wrong("g1")]
    world.plan[("full", "m")] = [wrong("g1"), wrong("g2"), wrong("g3")]
    serve_once(service, "session-cccc3333", "m", "gist")
    serve_once(service, "session-cccc3333", "m", "full")
    assert service.failures.count(("session", "session-cccc3333")) == 3
    assert service.failures.count(("ip", IP)) == 3
