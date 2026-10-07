import pytest

from gisting.eval.stats import mcnemar_p, upper_bound


@pytest.mark.parametrize(
    ("failures", "n", "expected"),
    [
        (0, 300, 0.009936),
        (0, 100, 0.029513),
        (0, 150, 0.019773),
        (1, 100, 0.046560),
        (5, 100, 0.102253),
        (10, 100, 0.163718),
    ],
)
def test_the_one_sided_exact_upper_bound_matches_known_values(
    failures: int, n: int, expected: float
) -> None:
    assert upper_bound(failures, n) == pytest.approx(expected, abs=2e-6)


def test_no_cases_say_nothing_so_the_bound_is_one() -> None:
    assert upper_bound(0, 0) == 1.0


def test_every_case_failing_gives_one() -> None:
    assert upper_bound(7, 7) == 1.0


@pytest.mark.parametrize(("failures", "n"), [(-1, 5), (6, 5)])
def test_impossible_counts_are_refused(failures: int, n: int) -> None:
    with pytest.raises(ValueError, match="failures"):
        upper_bound(failures, n)


def test_the_bound_never_falls_when_failures_grow() -> None:
    bounds = [upper_bound(k, 200) for k in range(0, 40)]
    assert bounds == sorted(bounds)


def test_mcnemar_with_no_discordant_pairs_is_not_significant() -> None:
    assert mcnemar_p(0, 0) == 1.0


def test_mcnemar_is_the_exact_two_sided_sign_test() -> None:
    assert mcnemar_p(0, 10) == pytest.approx(2 * 0.5**10)
    assert mcnemar_p(10, 0) == pytest.approx(2 * 0.5**10)
    assert mcnemar_p(5, 5) == 1.0
    assert mcnemar_p(2, 8) == pytest.approx(0.109375)


def test_mcnemar_is_symmetric_and_capped_at_one() -> None:
    assert mcnemar_p(3, 9) == mcnemar_p(9, 3)
    assert mcnemar_p(1, 1) == 1.0
