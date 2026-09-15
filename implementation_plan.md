# MetaJot Implementation Plan

This document outlines the architecture and implementation steps for MetaJot, a desktop Python application designed to automate the metadata tagging of `.jpg` files using AI models and format them for stock photo sites.

## Goal Description

The application will process a directory of `.jpg` images by reading their existing metadata (title, keywords, geolocation), sending the image and metadata to an AI model to generate rich titles, descriptions, and keywords, and finally writing the new metadata back to the image file. Secondary to this, it will generate appropriately formatted `.csv` files for Adobe Stock and Shutterstock uploads.

## Proposed Architecture & Dependencies

To keep the application modern, fast, and robust, we will break it down into several core modules:

### 1. Configuration Management (`src/metajot/config.py`)
- We will use a `config.toml` (or `yaml`) file to store the AI provider (OpenAI, Anthropic, etc.), model names, API keys (or read from `.env`), and system prompts.
- We will use Python's built-in `tomllib` (Python 3.11+) or a library like `pydantic-settings` to easily validate and load these configurations.

### 2. Image Metadata Handling (`src/metajot/metadata.py`)
- **Reading/Writing**: We will use a combination of `iptcinfo3` (for IPTC metadata like keywords and captions) and `exif` (for hardware/camera EXIF data like geolocation). This is a pure-Python approach that is known to work well with outputs from editors like Capture One.
- *Why this works:* Capture One primarily embeds Title, Description, and Keywords into standard IPTC/XMP fields, which `iptcinfo3` handles nicely, while standard GPS tags remain in the EXIF block.

### 3. AI Service Integration (`src/metajot/ai.py`)
- Instead of hardcoding the `openai` python package, we can use the `openai` library since its client can seamlessly point to other providers (like local models, xAI, etc.) just by changing the `base_url`. Alternatively, we can use a library like `litellm` which provides a unified interface for 100+ LLMs.
- We will encode the images to base64, construct the prompt using the data extracted from the photo, and ask the AI to return structured JSON containing `{ "title": "...", "description": "...", "keywords": ["..."] }`.

### 4. CSV Exporter (`src/metajot/exporter.py`)
- Utilizing Python's built-in `csv` module, we will generate two distinct CSV formatting functions tailored to the specific columns required by Adobe Stock and Shutterstock.

### 5. Orchestrator (`src/metajot/main.py`)
- A CLI (possibly using the `click` or `rich` library for nice progress bars) that iterates through a directory, tying all the above modules together.

## User Review Required

> [!IMPORTANT]  
> 1. **AI Configuration**: Do you prefer to store the `config.toml` in the project directory, or in a global user directory (e.g., `~/.metajot/config.toml`)?
> 2. **AI Interface**: Are you okay using the official `openai` Python package as our base, and just letting the config file override the `base_url` and `api_key` if you decide to use another compatible model in the future?

## Proposed Changes

### Configuration
#### [NEW] [config.py](file:///D:/a/metajot/src/metajot/config.py)
#### [NEW] [config.toml](file:///D:/a/metajot/config.toml)

### Modules
#### [NEW] [metadata.py](file:///D:/a/metajot/src/metajot/metadata.py)
#### [NEW] [ai.py](file:///D:/a/metajot/src/metajot/ai.py)
#### [NEW] [exporter.py](file:///D:/a/metajot/src/metajot/exporter.py)

### Main Application
#### [MODIFY] [main.py](file:///D:/a/metajot/src/metajot/main.py)

## Verification Plan

### Automated Tests
- Unit test the config loader.
- Unit test the CSV generation against known-good row outputs.
- Mock the AI response to ensure it parses the JSON correctly.

### Manual Verification
- We will drop a few sample `.jpg` files into a `tests/fixtures/` directory and manually run the app end-to-end to verify that the files are properly tagged when opened in Windows Explorer/Mac Finder.
