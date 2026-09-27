# MetaJot

MetaJot is a desktop Python (PySide6) app that automates metadata tagging of `.jpg` files for stock photo
sites. It reads a directory of images, reads their existing IPTC/EXIF metadata (title, keywords,
geolocation), sends each image plus that context to a vision-capable AI model to generate a rich
title/description/keywords, writes the new metadata back into the image file, and generates
Adobe Stock / Shutterstock compatible `.csv` upload sheets.

## Setup

1. **Install [uv](https://docs.astral.sh/uv/)** (Python env/dependency manager), if you don't
   already have it:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   This installs `uv` to `%USERPROFILE%\.local\bin` and adds it to your user `PATH`. Restart
   your terminal/IDE afterwards so the updated `PATH` takes effect.

2. **Install dependencies** (creates `.venv` using the Python version pinned in
   `.python-version`):

   ```bash
   uv sync
   ```

3. **Configure the AI provider.** Copy the example config and fill in your model/API key:

   ```bash
   cp config.toml.example config.toml
   ```

   `config.toml` is gitignored since it can hold a live API key. Prefer setting the
   `OPENAI_API_KEY` environment variable over putting the key in `config.toml` — the env var
   takes priority and keeps the key off disk.

## Usage

Run from the project root (see [Gotchas](#gotchas) below):

```bash
uv run metajot
```

This opens the desktop window. The workflow has three separate steps:

1. **Select Folder...** and click **Process with AI** to generate titles, descriptions,
   keywords, categories and a location for each photo (**Cancel** stops after the current
   photo). Click a thumbnail to see a photo's full metadata; click a column header to sort.
2. **Write Metadata** saves the generated metadata into the photo files (IPTC, mirrored to EXIF/XMP),
   including the location in the standard City / State-Province / Country fields.
3. **Export CSVs** generates `adobe_stock.csv` / `shutterstock.csv` in that folder.

The location comes from the location already embedded in the photo, then GPS
reverse-geocoding, then the AI's guess from keywords and the scene, in that priority order.
Since it's saved into the file, you can reopen a processed folder later, tick a photo's
**Editorial** checkbox, and export again without re-running the AI. Editorial rows get an
AP/Reuters-style dateline in the Shutterstock description
(`"City, State/Country - Month Day Year: Description"`) and are marked Editorial in the CSV.

## Development

```bash
uv run pytest -q                 # run the test suite
uv run pytest tests/test_config.py::test_config_loads_defaults  # run a single test
uv run ruff check src tests      # lint
uv run ruff check --fix src tests
```

## Gotchas

- `config.toml` is loaded relative to the **current working directory at runtime**, not the
  package location — `uv run metajot` must be invoked from the project root (where
  `config.toml` lives), or the AI calls will fail with a missing API key. Same applies if
  installed as a `uv tool`; only the `OPENAI_API_KEY` env var path is cwd-independent.
- `tests/fixtures/` contains real sample `.jpg` photos used for manual end-to-end verification —
  processing that folder mutates those files' embedded metadata in place.
