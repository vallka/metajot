from pathlib import Path

# pyproject.toml points pytest's --basetemp (and TEMP) into .tmp/, which is
# gitignored - so a fresh clone (e.g. CI) doesn't have it, and pytest won't
# create the missing parent itself.
(Path(__file__).resolve().parent.parent / ".tmp").mkdir(exist_ok=True)
