# Changelog

## 0.1.0 (unreleased)

First release.

- Pack a project into one Markdown or XML prompt with a directory tree.
- File selection that matches git exactly (`git ls-files`), with its own `.gitignore` parser outside git repositories.
- Skips lockfiles, build output, binaries, large files and credential files by default.
- Redacts API keys, tokens and private keys.
- Token estimate, largest-file summary and `--max-tokens` budget.
- `--exact`: exact Claude token counts through the Anthropic API (`pip install 'repofold[claude]'`).
- `--watch`: re-pack automatically when files change.
- Output to a file, the clipboard or stdout; `--dry-run` and `--tree-only`.
