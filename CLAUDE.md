# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MetaJot is a desktop Python CLI that automates metadata tagging of `.jpg` files for stock photo
sites. It reads a directory of images, reads their existing IPTC/EXIF metadata (title, keywords,
geolocation), sends each image plus that context to a vision-capable AI model to generate a rich
title/description/keywords, writes the new metadata back into the image file, and generates
Adobe Stock / Shutterstock compatible `.csv` upload sheets.

## Commands

This project uses `uv` for environment and dependency management (Python >=3.12, pinned via
`.python-version`).

```bash
uv sync                          # create/update .venv from uv.lock
uv run metajot "<photo-folder>"   # run the CLI — must be invoked from the project root (see Gotchas)
uv run pytest -q                 # run the test suite
uv run pytest tests/test_main.py::test_config_loads_defaults  # run a single test
uv run ruff check src tests      # lint
uv run ruff check --fix src tests
```

There is no separate build step (pure Python, hatchling backend).

## Architecture

Pipeline, orchestrated by `process_directory()` in [src/metajot/main.py](src/metajot/main.py):

1. **[metadata.py](src/metajot/metadata.py)** `read_metadata()` — reads existing IPTC fields
   (title/description/keywords via `iptcinfo3`) and EXIF GPS tags (via `exif`) from a `.jpg`.
2. **[ai.py](src/metajot/ai.py)** `generate_metadata()` — downscales the image with Pillow
   (`AIConfig.max_image_dimension`, default 1024px on the long edge) before base64-encoding it,
   builds a prompt from the existing metadata as context, and calls the OpenAI-compatible
   `chat.completions.parse` API with a Pydantic `AIResponse` schema (`title`, `description`,
   `keywords`) for structured output.
3. **[metadata.py](src/metajot/metadata.py)** `write_metadata()` — writes the AI-generated
   title/description/keywords back into the file's IPTC fields via `iptcinfo3`.
4. **[exporter.py](src/metajot/exporter.py)** — once all images are processed, writes
   `adobe_stock.csv` (Filename, Title, Keywords, Category) and `shutterstock.csv` (Filename,
   Description, Keywords, Categories) into the processed directory.

**[config.py](src/metajot/config.py)** loads `config.toml` (`[ai]` model/base_url/api_key/
max_image_dimension, `[prompts]` system_prompt) once at import time into a module-level `settings`
singleton, used by `ai.py`. `OPENAI_API_KEY` env var takes priority over `config.toml`'s `api_key`
so the key doesn't need to live on disk.

### Gotchas

- `CONFIG_PATH` in `config.py` is `Path("config.toml")` — resolved relative to the **current
  working directory at runtime**, not the package location. `uv run metajot` must be invoked from
  the project root (where `config.toml` lives) or the AI calls will fail with a missing API key.
  Same applies if installed as a `uv tool` — only the `OPENAI_API_KEY` env var path is cwd-independent.
- `iptcinfo3`'s `IPTCInfo.save()` writes the new data directly back to the original file path,
  moving the *previous* version to `<filename>~` as a backup by default (the reverse of what the
  name suggests at a glance). `write_metadata()` passes `options=["overwrite"]` to skip that
  backup entirely, since the old data isn't needed and the `~` files were just clutter.
- `config.toml` and `.env` are gitignored since `config.toml` holds a live API key in this
  environment; don't suggest committing them.
- `tests/fixtures/` contains real sample `.jpg` photos used for manual end-to-end verification
  (per the original implementation plan) — running the CLI against that directory mutates those
  files' embedded metadata in place.
