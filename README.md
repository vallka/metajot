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

3. **Enter your OpenAI API key** in the app: click **Settings...**, paste the key, and
   optionally click **Test**. The key is stored in the operating system's credential store
   (Windows Credential Manager / macOS Keychain), not in a file. The other settings (model,
   base URL, max image size) are saved to a per-user `config.toml`
   (`%LOCALAPPDATA%\MetaJot\config.toml` on Windows).

   Alternatively, set the `OPENAI_API_KEY` environment variable, which takes priority.

## Usage


```bash
uv run metajot
```

This opens the desktop window. The workflow has three separate steps:

1. **Select Folder...** (or pick one from **Open Recent**) and click **Process with AI** to generate titles, descriptions,
   keywords, categories and a location for the photos ticked in the **Process** column
   (pre-ticked for photos MetaJot hasn't processed yet; **Cancel** stops after the current
   photo). Click a thumbnail to see and edit a photo's metadata (title, description,
   keywords, location, categories); click a column header to sort. Edits made before
   processing - e.g. correcting a place name or adding a landmark to the keywords - are given
   to the AI as context; edits made after processing are kept as they are.
   The checkbox in the Process and Editorial column headers ticks/unticks all rows.
2. **Write Metadata** saves the generated metadata into the photo files (IPTC, mirrored to EXIF/XMP),
   including the location in the standard City / State-Province / Country fields, and the
   Editorial flag.
3. **Export CSVs** generates `adobe_stock.csv` / `shutterstock.csv` in that folder.

The location comes from the location already embedded in the photo, then GPS
reverse-geocoding, then the AI's guess from keywords and the scene, in that priority order.
Since it's saved into the file, you can reopen a processed folder later, tick a photo's
**Editorial** checkbox, and export again without re-running the AI. The Editorial flag is
saved in the photo too (by **Write Metadata**), so it's still set when the folder is reopened. Editorial rows get an
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

- A `config.toml` in the current working directory (the original setup, see
  `config.toml.example`) is still read, as a fallback below the per-user settings file, so
  its values only apply when the app is started from that folder.
- `tests/fixtures/` contains real sample `.jpg` photos used for manual end-to-end verification —
  processing that folder mutates those files' embedded metadata in place.
