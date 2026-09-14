import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class ExportRecord:
    filename: str
    title: str  # Used by Adobe
    description: str  # Used by Shutterstock
    keywords: List[str]
    adobe_category_id: str
    shutterstock_categories: List[str]
    # Whether this photo's description was formatted as an AP/Reuters-style
    # editorial dateline - drives Shutterstock's own "Editorial" CSV column.
    editorial: bool = False


def export_adobe_stock_csv(records: List[ExportRecord], output_path: Path) -> None:
    """
    Exports a list of records to an Adobe Stock compatible CSV file.
    Standard Headers: Filename, Options (auto, metadata), Title, Keywords, Category
    We use the simplest standard layout.
    """
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Filename", "Title", "Keywords", "Category"])

        for record in records:
            # Adobe requires keywords to be comma-separated strings
            keyword_str = ",".join(record.keywords)
            writer.writerow(
                [
                    record.filename,
                    record.title,
                    keyword_str,
                    record.adobe_category_id,
                ]
            )


def export_shutterstock_csv(records: List[ExportRecord], output_path: Path) -> None:
    """
    Exports a list of records to a Shutterstock compatible CSV file.
    Headers (order matters - Shutterstock matches columns positionally):
    Filename, Description, Keywords, Categories, Illustration, Mature
    Content, Editorial. The last three are officially optional, but Editorial
    is column G, so Illustration/Mature Content (E/F) must still be present
    to keep it in the right position.
    """
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Filename",
                "Description",
                "Keywords",
                "Categories",
                "Illustration",
                "Mature Content",
                "Editorial",
            ]
        )

        for record in records:
            # Shutterstock requires keywords to be comma-separated strings
            keyword_str = ",".join(record.keywords)
            # Shutterstock requires 1-2 categories, comma-separated
            category_str = ",".join(record.shutterstock_categories)
            writer.writerow(
                [
                    record.filename,
                    record.description,  # Shutterstock favors description over title
                    keyword_str,
                    category_str,
                    "No",  # Illustration - FotoAI only processes photographs
                    "No",  # Mature Content - not something FotoAI classifies
                    "Yes" if record.editorial else "No",
                ]
            )
