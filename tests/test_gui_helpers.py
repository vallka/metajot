from metajot.gui.detail_dialog import parse_keywords


def test_parse_keywords_splits_dedupes_and_keeps_order():
    text = "Scotland, Fife,\nKirkcaldy, kirkcaldy , , Ravenscraig Castle"
    assert parse_keywords(text) == [
        "Scotland",
        "Fife",
        "Kirkcaldy",
        "Ravenscraig Castle",
    ]


def test_parse_keywords_empty():
    assert parse_keywords(" , \n ") == []
