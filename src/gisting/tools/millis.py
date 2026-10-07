MS_PER_SECOND = 1000.0
MS_DIGITS = 1


def seconds_to_ms(seconds: float) -> float:
    return seconds * MS_PER_SECOND


def round_ms(milliseconds: float) -> float:
    return round(milliseconds, MS_DIGITS)
