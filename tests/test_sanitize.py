from fotoai.sanitize import (
    sanitize_shutterstock_description,
    sanitize_typography,
    to_ascii,
)


def test_sanitize_typography_replaces_em_and_en_dash():
    assert sanitize_typography("a — b – c") == "a - b - c"


def test_sanitize_typography_replaces_curly_quotes_and_ellipsis():
    assert (
        sanitize_typography("“quoted” and ‘it’s’…")
        == '"quoted" and \'it\'s\'...'
    )


def test_sanitize_typography_leaves_plain_ascii_untouched():
    text = "Plain ASCII - no changes."
    assert sanitize_typography(text) == text


def test_to_ascii_transliterates_accented_characters():
    assert to_ascii("Café só Zürich") == "Cafe so Zurich"


def test_sanitize_shutterstock_description_strips_banned_chars():
    result = sanitize_shutterstock_description("Cats & dogs <playing> indoor/outdoor")
    assert result == "Cats and dogs playing indoor outdoor"
    assert not any(c in result for c in "<>&/")


def test_sanitize_shutterstock_description_collapses_whitespace():
    assert sanitize_shutterstock_description("a / b") == "a b"
