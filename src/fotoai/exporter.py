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
    Standard Headers: Filename, Description, Keywords, Categories
    """
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Filename", "Description", "Keywords", "Categories"])

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
                ]
            )
