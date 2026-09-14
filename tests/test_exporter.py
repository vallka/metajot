import csv

from fotoai.exporter import ExportRecord, export_shutterstock_csv


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_export_shutterstock_csv_header_matches_shutterstock_spec(tmp_path):
    output = tmp_path / "shutterstock.csv"
    export_shutterstock_csv([], output)

    rows = _read_csv(output)
    assert rows[0] == [
        "Filename",
        "Description",
        "Keywords",
        "Categories",
        "Illustration",
        "Mature Content",
        "Editorial",
    ]


def test_export_shutterstock_csv_editorial_column_yes_when_flagged(tmp_path):
    record = ExportRecord(
        filename="a.jpg",
        title="T",
        description="Edinburgh, UK - August 30, 2025: A harbour scene.",
        keywords=["k1", "k2"],
        adobe_category_id="1",
        shutterstock_categories=["Nature"],
        editorial=True,
    )
    output = tmp_path / "shutterstock.csv"
    export_shutterstock_csv([record], output)

    rows = _read_csv(output)
    assert rows[1][-1] == "Yes"
    assert rows[1][-3:-1] == ["No", "No"]  # Illustration, Mature Content


def test_export_shutterstock_csv_editorial_column_no_by_default(tmp_path):
    record = ExportRecord(
        filename="a.jpg",
        title="T",
        description="A harbour scene.",
        keywords=["k1"],
        adobe_category_id="1",
        shutterstock_categories=["Nature"],
    )
    output = tmp_path / "shutterstock.csv"
    export_shutterstock_csv([record], output)

    rows = _read_csv(output)
    assert rows[1][-1] == "No"
