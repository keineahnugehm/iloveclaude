# repofold

**Fold your whole codebase into one prompt. Paste it into Claude, ChatGPT or Gemini. Done.**

<p align="center">
  <img src="docs/demo.svg" alt="repofold packing a project: 8 files included, a binary and a .env skipped, an API key redacted, then the directory tree as XML">
</p>

Asking an LLM about a codebase usually starts with copy-pasting files one at a time. repofold replaces that with
one command: it packs the project into a single Markdown or XML document with a directory tree, and it
respects `.gitignore`, skips the junk, counts tokens, and **redacts API keys before they leave your machine**.

- **Zero dependencies.** Pure Python 3.9+ standard library. Linux, macOS and Windows.
- **Gitignore-exact.** Inside a git repo it asks git which files count. Elsewhere it uses its own `.gitignore` parser, including nested files.
- **No junk.** Skips lockfiles, `node_modules`, build output, minified bundles, binaries and huge files by default.
- **Secret-safe.** Skips `.env` and key files, and redacts AWS, GitHub, Anthropic, OpenAI, Google, Slack, Stripe and Hugging Face tokens, JWTs and private keys.
- **Token-aware.** Shows the token count and the largest files, `--max-tokens 100k` keeps the output inside a budget, and `--exact` gets the exact count for a Claude model.
- **Live.** `--watch` re-packs every time you save, so the file you hand to the model is never stale.
- **LLM-friendly output.** Markdown with collision-proof code fences, or XML tags (`-f xml`), which [Claude handles particularly well](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags).

## Install

```bash
pipx install repofold            # or: uv tool install repofold
uvx repofold                     # run it once without installing
pipx install 'repofold[claude]'  # adds --exact (installs the Anthropic SDK)
```

The latest development version installs straight from GitHub:
`pipx install git+https://github.com/keineahnugehm/iloveclaude`

## Usage

```bash
repofold                        # pack the current directory into repofold-output.md
repofold -c                     # ...straight to the clipboard
repofold ../other-project -f xml -o context.xml
repofold src -i '*.py' -i '*.toml'   # only some files (globs match the full path)
repofold -e 'tests/*' -e '*.snap'    # leave things out
repofold --max-tokens 150k      # fit a context window
repofold -n                     # dry run: just show files and token counts
repofold -n --exact             # ...with the exact token count for Claude
repofold -w -o context.md       # keep context.md up to date while you work
repofold --tree-only -c         # only the directory structure
repofold | llm "Find the bug"   # pipes work too: output goes to stdout when it isn't a terminal
```

| Option | What it does |
| --- | --- |
| `-o FILE` | Write to a file (default when on a terminal: `repofold-output.md`) |
| `-c`, `--copy` | Copy to the clipboard (pbcopy, wl-copy, xclip, xsel or clip.exe) |
| `--stdout` | Force output to stdout |
| `-f markdown\|xml` | Output format |
| `-i GLOB` / `-e GLOB` | Include / exclude paths, repeatable |
| `--max-tokens N` | Token budget for file contents (`100k`, `1m`, …) |
| `--max-file-size SIZE` | Skip files larger than this (default `1m`) |
| `--exact` | Exact token count from the Anthropic API (see below) |
| `--model MODEL` | Model for `--exact` (default `claude-opus-5-5`) |
| `-w`, `--watch` | Re-pack whenever a file changes, until Ctrl+C |
| `--interval SECONDS` | How often `--watch` checks for changes (default `1`) |
| `--tree-only` | Only print the directory tree |
| `-n`, `--dry-run` | Show the summary, write nothing |
| `--top N` | Number of largest files listed in the summary |
| `--no-gitignore` | Ignore `.gitignore` rules |
| `--no-default-excludes` | Also pack lockfiles, build output and credential files |
| `--no-redact` | Keep secrets as they are (be careful) |
| `-q` | No summary |

### Exact token counts for Claude

The built-in count is an estimate. For the exact number, install the extra and pass `--exact`:

```bash
pipx install 'repofold[claude]'
export ANTHROPIC_API_KEY=...     # or sign in once with `ant auth login`
repofold -n --exact              # tokens    48,213 (exact, claude-opus-5-5)
repofold -n --exact --model claude-sonnet-5-5
```

This uses Anthropic's free [token counting endpoint](https://docs.anthropic.com/en/docs/build-with-claude/token-counting),
which means **the packed text is sent to Anthropic** (after redaction). Without `--exact`, repofold never touches the
network.

## Output

<details>
<summary>Markdown (default)</summary>

````markdown
# my-app

2 files · ~7 tokens · packed with repofold

## Directory structure

```
├── src/
│   └── main.py
└── README.md
```

## Files

### README.md

```markdown
# my-app
```

### src/main.py

```python
print("hello")
```
````
</details>

<details>
<summary>XML (<code>-f xml</code>)</summary>

```xml
<repository name="my-app" files="2" approx_tokens="7">
<directory_structure>
├── src/
│   └── main.py
└── README.md
</directory_structure>
<files>
<file path="README.md">
# my-app
</file>
<file path="src/main.py">
print("hello")
</file>
</files>
</repository>
```
</details>

## As a library

```python
from repofold import collect, redact, render_xml

result = collect(".", include=["*.py"])
for f in result.files:
    f.content, _ = redact(f.content)
prompt = render_xml("my-app", result.files)
```

## FAQ

**How accurate is the token count?** By default it's a rough estimate of about 4 characters per token, which is
good enough to tell whether something fits a context window and needs no network access. Use `--exact` when
you need the real number for a Claude model.

**Is redaction a guarantee?** No. It catches the common, well-structured key formats. Review the output before
sharing anything sensitive. Generic passwords such as `password = "hunter2"` aren't detected.

**Why not just `cat` everything?** That would also pull in `node_modules`, lockfiles, binaries and your `.env`, the
model wouldn't know where one file ends and the next begins, and you'd have no idea whether it fits the
context window.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). If repofold saves you time, a ⭐
helps other people find it.

## License

[MIT](LICENSE)
