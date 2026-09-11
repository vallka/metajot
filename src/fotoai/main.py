import argparse
from pathlib import Path

from rich.console import Console
from rich.progress import track

from fotoai.ai import ADOBE_CATEGORY_IDS, generate_metadata
from fotoai.exporter import (
    ExportRecord,
    export_adobe_stock_csv,
    export_shutterstock_csv,
)
from fotoai.metadata import read_metadata, write_metadata

console = Console()


def process_directory(directory: Path) -> None:
    if not directory.is_dir():
        console.print(f"[red]Error: {directory} is not a valid directory.[/red]")
        return

    images = list(directory.glob("*.jpg")) + list(directory.glob("*.jpeg"))
    # Also include uppercase extensions just in case
    images += list(directory.glob("*.JPG")) + list(directory.glob("*.JPEG"))
    
    # Remove duplicates from case-insensitive match on Windows
    images = list(set(images))

    if not images:
        console.print(f"[yellow]No .jpg or .jpeg images found in {directory}[/yellow]")
        return

    console.print(f"[bold green]Found {len(images)} images in {directory}[/bold green]")

    records = []

    for img_path in track(images, description="Processing images..."):
        try:
            # 1. Read existing metadata
            current_meta = read_metadata(img_path)

            # 2. Call AI for rich metadata
            ai_data = generate_metadata(img_path, current_meta)

            adobe_category_id = str(ADOBE_CATEGORY_IDS[ai_data.adobe_category.value])
            shutterstock_categories = [ai_data.shutterstock_category_primary.value]
            if ai_data.shutterstock_category_secondary:
                shutterstock_categories.append(
                    ai_data.shutterstock_category_secondary.value
                )

            # 3. Write generated metadata back to the image
            success = write_metadata(
                img_path,
                ai_data.title,
                ai_data.description,
                ai_data.keywords,
                adobe_category_id,
                shutterstock_categories,
            )

            if success:
                records.append(
                    ExportRecord(
                        filename=img_path.name,
                        title=ai_data.title,
                        description=ai_data.description,
                        keywords=ai_data.keywords,
                        adobe_category_id=adobe_category_id,
                        shutterstock_categories=shutterstock_categories,
                    )
                )
            else:
                console.print(f"[red]Failed to write metadata to {img_path.name}[/red]")

        except Exception as e:
            console.print(f"[red]Error processing {img_path.name}: {e}[/red]")

    # 4. Generate CSVs
    if records:
        adobe_csv = directory / "adobe_stock.csv"
        shutter_csv = directory / "shutterstock.csv"

        export_adobe_stock_csv(records, adobe_csv)
        export_shutterstock_csv(records, shutter_csv)

        console.print(
            f"\n[bold green]Successfully processed {len(records)} images![/bold green]"
        )
        console.print(
            f"CSVs generated: [cyan]{adobe_csv.name}[/cyan] and [cyan]{shutter_csv.name}[/cyan]"
        )


def main():
    parser = argparse.ArgumentParser(
        description="FotoAI: AI-powered metadata tagger for stock photos."
    )
    parser.add_argument(
        "directory", type=Path, help="Directory containing .jpg files to process"
    )

    args = parser.parse_args()
    process_directory(args.directory)


if __name__ == "__main__":
    main()
