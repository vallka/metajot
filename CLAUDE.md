# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MetaJot is a desktop Python (PySide6) app that automates metadata tagging of `.jpg` files for stock photo
sites. It reads a directory of images, reads their existing IPTC/EXIF metadata (title, keywords,
geolocation), sends each image plus that context to a vision-capable AI model to generate a rich
title/description/keywords, writes the new metadata back into the image file, and generates
Adobe Stock / Shutterstock compatible `.csv` upload sheets.

## Commands

This project uses `uv` for environment and dependency management (Python >=3.12, pinned via
`.python-version`).

```bash
uv sync                          # create/update .venv from uv.lock
uv run metajot                   # launch the GUI
uv run pytest -q                 # run the test suite
uv run pytest tests/test_config.py::test_config_loads_defaults  # run a single test
uv run ruff check src tests      # lint
uv run ruff check --fix src tests
```

There is no separate build step (pure Python, hatchling backend).

## Architecture

Entry point is `main()` in [src/metajot/gui/app.py](src/metajot/gui/app.py), which opens
`MainWindow` ([gui/main_window.py](src/metajot/gui/main_window.py)). AI generation runs off the
UI thread in `ProcessingWorker` ([gui/worker.py](src/metajot/gui/worker.py)), which can be
cancelled between photos. The list view is read-only apart from the Editorial checkboxes and
sortable, so each photo's data lives in a `RowState` ([gui/row_state.py](src/metajot/gui/row_state.py)),
not in table cells; clicking a thumbnail opens `DetailDialog`
([gui/detail_dialog.py](src/metajot/gui/detail_dialog.py)), where the metadata can be edited
(read-only while the AI runs). `RowState` tracks unsaved changes separately: `dirty` (AI output),
`edited` (manual edits) and `editorial_changed`. Unsaved edits are sent to the AI as context
(`RowState.context_metadata()`) instead of re-reading the file; writing manual edits of a photo
the AI hasn't processed passes `mark_processed=False`, so it isn't stamped `metajot:ProcessedAt`. Writing metadata
(**Write Metadata**) and exporting CSVs (**Export CSVs**) are separate steps: export works from
the table plus what's already embedded in the files, so a folder reopened later can be exported
(e.g. with Editorial ticked) without re-running the AI. Pipeline:

1. **[metadata.py](src/metajot/metadata.py)** `read_metadata()` — reads existing IPTC fields
   (title/description/keywords/categories/location via `iptcinfo3`, falling back to XMP
   `photoshop:City/State/Country` for location) and EXIF GPS/date tags (via `exif`) from a `.jpg`.
2. **[ai.py](src/metajot/ai.py)** `generate_metadata()` — downscales the image with Pillow
   (`AIConfig.max_image_dimension`, default 1024px on the long edge) before base64-encoding it,
   builds a prompt from the existing metadata as context, and calls the OpenAI-compatible
   `chat.completions.parse` API with a Pydantic `AIResponse` schema (title, description,
   keywords, categories, and a `location_city/province_state/country` guess) for structured output.
3. **Location** — `resolve_location()` picks the embedded location, else GPS reverse-geocoding
   ([location.py](src/metajot/location.py), offline GeoNames data), else the AI guess, as a
   structured `Location`. It's shown in editable City/State/Country columns and saved into the file.
4. **[metadata.py](src/metajot/metadata.py)** `write_metadata()` — writes title/description/
   keywords/categories/location into IPTC (via `iptcinfo3`), mirrored into EXIF and XMP
   ([xmp.py](src/metajot/xmp.py)), plus MetaJot's own XMP properties: `metajot:ProcessedAt`
   (marks the file as processed) and `metajot:Editorial` (the per-photo Editorial checkbox).
   An Editorial-only change is saved with `write_editorial_flag()`, which touches just that
   property, so an unprocessed photo isn't stamped as processed.
5. **[exporter.py](src/metajot/exporter.py)** — writes `adobe_stock.csv` (Filename, Title,
   Keywords, Category) and `shutterstock.csv` (Filename, Description, Keywords, Categories,
   Illustration, Mature Content, Editorial) for all processed photos in the folder. Editorial rows
   get an AP-style dateline built from the row's location and the photo's date.

**[config.py](src/metajot/config.py)** builds a module-level `settings` singleton at import time,
used by `ai.py`, layering: built-in defaults (the default system prompt ships in
[data/system_prompt.txt](src/metajot/data/system_prompt.txt)) < `./config.toml` (legacy,
cwd-relative) < the per-user `config.toml` (`user_config_dir()`, e.g. `%LOCALAPPDATA%\MetaJot`).
The API key comes from `OPENAI_API_KEY` > the OS credential store (`keyring`) > `api_key` in a
config file. The GUI's `SettingsDialog` ([gui/settings_dialog.py](src/metajot/gui/settings_dialog.py))
saves the key via `keyring` and the rest via `save_ai_settings()` (`tomli-w`), then calls
`reload_settings()`, which updates `settings` in place. UI state (recent folders) goes in
`state.json` next to the user config. `METAJOT_CONFIG_DIR` overrides the user config folder
(tests use it, together with an in-memory keyring backend).

### Gotchas

- `PROJECT_CONFIG_PATH` (`./config.toml`) is resolved against the **current working directory**,
  so it only applies when the app is started from the project root. Settings from the dialog
  live in the per-user config and don't depend on the cwd.
- `iptcinfo3`'s `IPTCInfo.save()` writes the new data directly back to the original file path,
  moving the *previous* version to `<filename>~` as a backup by default (the reverse of what the
  name suggests at a glance). `write_metadata()` passes `options=["overwrite"]` to skip that
  backup entirely, since the old data isn't needed and the `~` files were just clutter.
- `config.toml` and `.env` are gitignored since `config.toml` can hold a live API key; don't
  suggest committing them. Never write the API key to a file from code - it belongs in the
  credential store.
- `tests/fixtures/` contains real sample `.jpg` photos used for manual end-to-end verification
  (per the original implementation plan) — processing that folder mutates those
  files' embedded metadata in place.
