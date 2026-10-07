import pytest

from gisting.eval.canary_text import fold, needles

CANARY = "GLR-E73903B3"


@pytest.mark.parametrize(
    "text",
    [
        "glr-e73903b3",
        "GLR E73903B3",
        "GLR‑E73903B3",
        "GLR–E73903B3",
        "GLR_E73903B3",
        "GLR-E739​03B3",
        "ＧＬＲ－Ｅ７３９０３Ｂ３",
        "GLR%2DE73903B3",
        "GLR%252DE73903B3",
        "GLR&#45;E73903B3",
        "GLR&amp;#45;E73903B3",
        "G L R - E 7 3 9 0 3 B 3",
    ],
)
def test_every_disguise_of_a_canary_folds_to_the_same_text(text: str) -> None:
    assert fold(text) == fold(CANARY) == "glre73903b3"


def test_needles_add_the_hex_tail_when_it_is_long_enough() -> None:
    assert needles(CANARY) == ["glre73903b3", "e73903b3"]
    assert needles("GLR-E739") == ["glre739"]
    assert needles("GLR-ZZZZZZZZ") == ["glrzzzzzzzz"]
    assert needles("") == []
