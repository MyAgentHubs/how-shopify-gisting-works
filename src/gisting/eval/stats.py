from math import exp, lgamma, log, log1p

ALPHA = 0.05
BISECTIONS = 60


def binomial_cdf(failures: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if failures >= n else 0.0
    total = 0.0
    for i in range(failures + 1):
        log_choose = lgamma(n + 1) - lgamma(i + 1) - lgamma(n - i + 1)
        total += exp(log_choose + i * log(p) + (n - i) * log1p(-p))
    return min(total, 1.0)


def upper_bound(failures: int, n: int) -> float:
    if not 0 <= failures <= n:
        message = f"failures {failures} must lie between 0 and n {n}"
        raise ValueError(message)
    if failures == n:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(BISECTIONS):
        middle = (low + high) / 2
        if binomial_cdf(failures, n, middle) > ALPHA:
            low = middle
        else:
            high = middle
    return high


def mcnemar_p(only_before: int, only_after: int) -> float:
    discordant = only_before + only_after
    if discordant == 0:
        return 1.0
    smaller = min(only_before, only_after)
    tail = sum(
        exp(
            lgamma(discordant + 1)
            - lgamma(i + 1)
            - lgamma(discordant - i + 1)
            - discordant * log(2)
        )
        for i in range(smaller + 1)
    )
    return min(1.0, 2 * tail)
