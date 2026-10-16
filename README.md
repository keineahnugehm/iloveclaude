# ctxpack

**Pack your whole codebase into one prompt. Paste it into Claude, ChatGPT or Gemini. Done.**

```console
$ ctxpack -c
ctxpack · my-app
  files     84 included (3 binary, 1 credential files skipped)
  tokens    ~61,240
  redacted  2 secret(s): aws-access-key×1, github-token×1
  largest
    ~   6,812  src/server/routes.ts
    ~   4,105  src/db/schema.ts
    ~   3,377  src/ui/Dashboard.tsx
  output    clipboard
```

Asking an LLM about a codebase usually starts with copy-pasting files one at a time. ctxpack replaces that with
one command: it packs the project into a single Markdown or XML document with a directory tree, and it
respects `.gitignore`, skips the junk, counts tokens, and **redacts API keys before they leave your machine**.

- **Zero dependencies.** Pure Python 3.9+ standard library. Linux, macOS and Windows.
- **Gitignore-exact.** Inside a git repo it asks git which files count. Elsewhere it uses its own `.gitignore` parser, including nested files.
- **No junk.** Skips lockfiles, `node_modules`, build output, minified bundles, binaries and huge files by default.
- **Secret-safe.** Skips `.env` and key files, and redacts AWS, GitHub, Anthropic, OpenAI, Google, Slack, Stripe and Hugging Face tokens, JWTs and private keys.
- **Token-aware.** Shows the token count and the largest files, and `--max-tokens 100k` keeps the output inside a budget.
- **LLM-friendly output.** Markdown with collision-proof code fences, or XML tags (`-f xml`), which [Claude handles particularly well](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags).

## Install

```bash
pipx install git+https://github.com/keineahnugehm/iloveclaude
# or run it without installing:
uvx --from git+https://github.com/keineahnugehm/iloveclaude ctxpack
```

## Usage

```bash
ctxpack                        # pack the current directory into ctxpack-output.md
ctxpack -c                     # ...straight to the clipboard
ctxpack ../other-project -f xml -o context.xml
ctxpack src -i '*.py' -i '*.toml'   # only some files (globs match the full path)
ctxpack -e 'tests/*' -e '*.snap'    # leave things out
ctxpack --max-tokens 150k      # fit a context window
ctxpack -n                     # dry run: just show files and token counts
ctxpack --tree-only -c         # only the directory structure
ctxpack | llm "Find the bug"   # pipes work too: output goes to stdout when it isn't a terminal
```

| Option | What it does |
| --- | --- |
| `-o FILE` | Write to a file (default when on a terminal: `ctxpack-output.md`) |
| `-c`, `--copy` | Copy to the clipboard (pbcopy, wl-copy, xclip, xsel or clip.exe) |
| `--stdout` | Force output to stdout |
| `-f markdown\|xml` | Output format |
| `-i GLOB` / `-e GLOB` | Include / exclude paths, repeatable |
| `--max-tokens N` | Token budget for file contents (`100k`, `1m`, …) |
| `--max-file-size SIZE` | Skip files larger than this (default `1m`) |
| `--tree-only` | Only print the directory tree |
| `-n`, `--dry-run` | Show the summary, write nothing |
| `--top N` | Number of largest files listed in the summary |
| `--no-gitignore` | Ignore `.gitignore` rules |
| `--no-default-excludes` | Also pack lockfiles, build output and credential files |
| `--no-redact` | Keep secrets as they are (be careful) |
| `-q` | No summary |

## Output

<details>
<summary>Markdown (default)</summary>

````markdown
# my-app

2 files · ~42 tokens · packed with ctxpack

## Directory structure

```
├── src/
│   └── main.py
└── README.md
```

## Files

### src/main.py

```python
print("hello")
```
````
</details>

<details>
<summary>XML (<code>-f xml</code>)</summary>

```xml
<repository name="my-app" files="2" approx_tokens="42">
<directory_structure>
├── src/
│   └── main.py
└── README.md
</directory_structure>
<files>
<file path="src/main.py">
print("hello")
</file>
</files>
</repository>
```
</details>

## As a library

```python
from ctxpack import collect, redact, render_xml

result = collect(".", include=["*.py"])
for f in result.files:
    f.content, _ = redact(f.content)
prompt = render_xml("my-app", result.files)
```

## FAQ

**How accurate is the token count?** It's a rough estimate of about 4 characters per token, which is good
enough to tell whether something fits a context window. ctxpack deliberately doesn't depend on any one model's
tokenizer.

**Is redaction a guarantee?** No. It catches the common, well-structured key formats. Review the output before
sharing anything sensitive. Generic passwords such as `password = "hunter2"` aren't detected.

**Why not just `cat` everything?** That would also pull in `node_modules`, lockfiles, binaries and your `.env`, the
model wouldn't know where one file ends and the next begins, and you'd have no idea whether it fits the
context window.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). If ctxpack saves you time, a ⭐
helps other people find it.

## License

[MIT](LICENSE)
