"""Reading and editing dotenv text without disturbing other lines."""

from tessaro_seed.envfile import read_env, set_env


def test_read_skips_comments_blanks_and_strips_one_pair_of_quotes() -> None:
    text = "# c\n\nA=1\nB='two words'\nC=\"x\"\nD=\nnot a line\n"
    assert read_env(text) == {"A": "1", "B": "two words", "C": "x", "D": ""}


def test_read_keeps_the_last_of_duplicate_names() -> None:
    assert read_env("A=1\nA=2\n") == {"A": "2"}


def test_set_replaces_in_place_appends_new_and_drops_duplicates() -> None:
    text = "# c\nA=1\nB=2\nA=3\n"
    assert set_env(text, {"A": "x", "C": "y"}) == "# c\nA=x\nB=2\nC=y\n"


def test_set_on_empty_text_writes_only_the_values() -> None:
    assert set_env("", {"A": "1"}) == "A=1\n"


def test_a_commented_out_name_is_not_replaced() -> None:
    assert set_env("# A=old\n", {"A": "new"}) == "# A=old\nA=new\n"
