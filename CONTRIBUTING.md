# Contributing

Thanks for helping out! repofold aims to stay small, fast and dependency-free.

```bash
git clone https://github.com/keineahnugehm/iloveclaude && cd iloveclaude
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest ruff==0.16.8
pytest && ruff check .
```

- **New secret format?** Add a pattern to `src/repofold/redact.py` and a test. Build fake tokens at runtime
  (`"ghp_" + "x" * 36`) so the test file doesn't trip GitHub's secret scanning.
- **New language for code fences?** Add the extension to `LANGUAGES` in `src/repofold/render.py`.
- **Bigger changes:** please open an issue first so we can agree on the approach.
- Keep runtime dependencies at zero.
