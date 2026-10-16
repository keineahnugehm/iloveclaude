"""Command-line interface for repofold."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .claude import DEFAULT_MODEL, TokenCountError, count_tokens
from .collect import Collection, FileEntry, collect
from .redact import redact
from .render import RENDERERS, estimate_tokens
from .watch import watch

EXTENSIONS = {"markdown": "md", "xml": "xml"}


def parse_size(value: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?)b?\s*", value.lower())
    if not m:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r} (try 500k or 2m)")
    factor = {"": 1, "k": 1_000, "m": 1_000_000, "g": 1_000_000_000}[m.group(2)]
    return int(float(m.group(1)) * factor)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repofold",
        description="Pack a codebase into a single LLM-ready prompt.",
        epilog="examples:\n"
               "  repofold                      pack the current directory\n"
               "  repofold -c                   ...and copy it to the clipboard\n"
               "  repofold src -i '*.py'        only Python files under src/\n"
               "  repofold --max-tokens 100k    stay inside a token budget\n"
               "  repofold -n                   just show what would be packed\n"
               "  repofold -n --exact           ...with an exact Claude token count\n"
               "  repofold -w -o ctx.md         keep ctx.md up to date while you work",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("path", nargs="?", default=".", help="project directory (default: .)")
    p.add_argument("-o", "--output", help="write to this file")
    p.add_argument("-c", "--copy", action="store_true", help="copy the result to the clipboard")
    p.add_argument("--stdout", action="store_true", help="write to stdout even on a terminal")
    p.add_argument("-f", "--format", choices=sorted(RENDERERS), default="markdown",
                   help="output format (default: markdown; xml suits Claude well)")
    p.add_argument("-i", "--include", action="append", metavar="GLOB",
                   help="only include matching paths (repeatable)")
    p.add_argument("-e", "--exclude", action="append", metavar="GLOB",
                   help="exclude matching paths (repeatable)")
    p.add_argument("--max-file-size", type=parse_size, default=parse_size("1m"), metavar="SIZE",
                   help="skip files larger than this (default: 1m)")
    p.add_argument("--max-tokens", type=parse_size, metavar="N",
                   help="token budget for file contents; files that don't fit are left out (e.g. 100k)")
    p.add_argument("--tree-only", action="store_true", help="only output the directory tree")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="print the summary without producing output")
    p.add_argument("--exact", action="store_true",
                   help="count tokens exactly with the Anthropic API; sends the packed text "
                        "to Anthropic (needs repofold[claude] and an API key)")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"model for --exact (default: {DEFAULT_MODEL})")
    p.add_argument("-w", "--watch", action="store_true",
                   help="re-pack whenever a file changes (Ctrl+C to stop)")
    p.add_argument("--interval", type=float, default=1.0, metavar="SECONDS",
                   help="how often --watch checks for changes (default: 1)")
    p.add_argument("--top", type=int, default=5, metavar="N",
                   help="list the N largest files in the summary (default: 5)")
    p.add_argument("--no-gitignore", action="store_true", help="ignore .gitignore rules")
    p.add_argument("--no-default-excludes", action="store_true",
                   help="also pack lockfiles, build output and credential files")
    p.add_argument("--no-redact", action="store_true", help="don't redact detected secrets")
    p.add_argument("-q", "--quiet", action="store_true", help="no summary on stderr")
    p.add_argument("-V", "--version", action="version", version=f"repofold {__version__}")
    return p


def copy_to_clipboard(text: str) -> None:
    candidates = [
        ["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"], ["clip.exe"], ["clip"],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            # Windows' clip.exe only reads Unicode reliably as UTF-16 with a BOM.
            data = ("\ufeff" + text).encode("utf-16le") if cmd[0].startswith("clip") \
                else text.encode("utf-8")
            subprocess.run(cmd, input=data, check=True)
            return
    raise RuntimeError("no clipboard tool found (install wl-clipboard, xclip or xsel)")


class _Style:
    def __init__(self, stream) -> None:
        self.on = stream.isatty() and not os.environ.get("NO_COLOR")

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text


def apply_budget(files, budget: int):
    """Greedily keep files (in path order) while they fit in the token budget."""
    kept, dropped, used = [], [], 0
    for f in files:
        tokens = estimate_tokens(f.content)
        if used + tokens <= budget:
            kept.append(f)
            used += tokens
        else:
            dropped.append(f.path)
    return kept, dropped


@dataclass
class Packed:
    name: str
    result: Collection
    files: list[FileEntry]
    dropped: list[str]
    redactions: dict[str, int]
    text: str
    exact_tokens: int | None = None
    token_error: str | None = None


def pack(args: argparse.Namespace, root: Path, output: Path | None) -> Packed:
    result = collect(
        root,
        include=args.include,
        exclude=args.exclude,
        use_default_excludes=not args.no_default_excludes,
        respect_gitignore=not args.no_gitignore,
        max_file_bytes=args.max_file_size,
        skip_paths={output} if output else None,
    )

    redactions: dict[str, int] = {}
    if not args.no_redact:
        for f in result.files:
            f.content, counts = redact(f.content)
            for kind, n in counts.items():
                redactions[kind] = redactions.get(kind, 0) + n

    files, dropped = result.files, []
    if args.max_tokens is not None:
        files, dropped = apply_budget(files, args.max_tokens)

    name = result.root.name or str(result.root)
    text = RENDERERS[args.format](name, files, tree_only=args.tree_only)
    packed = Packed(name, result, files, dropped, redactions, text)
    if args.exact:
        try:
            packed.exact_tokens = count_tokens(text, args.model)
        except TokenCountError as exc:
            packed.token_error = str(exc)
    return packed


def emit(args: argparse.Namespace, packed: Packed, output: Path | None, to_stdout: bool) -> int:
    if args.dry_run:
        return 0
    if output:
        with open(output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(packed.text)
    if args.copy:
        try:
            copy_to_clipboard(packed.text)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            print(f"repofold: could not copy to clipboard: {exc}", file=sys.stderr)
            return 1
    if to_stdout:
        # Pipes on Windows default to a legacy code page that can't encode the tree.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        sys.stdout.write(packed.text)
        sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        print(f"repofold: not a directory: {root}", file=sys.stderr)
        return 2
    if args.interval <= 0:
        print("repofold: --interval must be positive", file=sys.stderr)
        return 2

    to_stdout = args.stdout or (not args.output and not args.copy and not sys.stdout.isatty())
    output = Path(args.output) if args.output else None
    if not output and not args.copy and not to_stdout and not args.dry_run:
        output = Path(f"repofold-output.{EXTENSIONS[args.format]}")

    def run_once() -> int:
        packed = pack(args, root, output)
        status = emit(args, packed, output, to_stdout)
        if not args.quiet:
            _print_summary(args, packed, output, to_stdout)
        elif packed.token_error:
            print(f"repofold: exact token count failed: {packed.token_error}", file=sys.stderr)
        return status or (1 if packed.token_error else 0)

    status = run_once()
    if not args.watch:
        return status

    def rerun() -> None:
        if not args.quiet:
            print(f"\n↻ {time.strftime('%H:%M:%S')} change detected", file=sys.stderr)
        run_once()

    if not args.quiet:
        print(f"\nwatching {root.resolve()} for changes (Ctrl+C to stop)", file=sys.stderr)
    try:
        watch(root, rerun, interval=args.interval, ignore=[output] if output else [])
    except KeyboardInterrupt:
        pass
    return 0


def _print_summary(args: argparse.Namespace, packed: Packed, output: Path | None,
                   to_stdout: bool) -> None:
    s = _Style(sys.stderr)
    result, files = packed.result, packed.files
    lines = [f"{s('repofold', '1')} · {packed.name}"]

    skipped = []
    if result.skipped_binary:
        skipped.append(f"{len(result.skipped_binary)} binary")
    if result.skipped_large:
        skipped.append(f"{len(result.skipped_large)} too large")
    if result.skipped_secret_files:
        n = len(result.skipped_secret_files)
        skipped.append(f"{n} credential file{'' if n == 1 else 's'}")
    if packed.dropped:
        skipped.append(f"{len(packed.dropped)} over budget")
    detail = f" ({', '.join(skipped)} skipped)" if skipped else ""
    lines.append(f"  {s('files', '2')}     {len(files)} included{detail}")

    if packed.exact_tokens is not None:
        tokens = f"{packed.exact_tokens:,} (exact, {args.model})"
    else:
        tokens = f"~{estimate_tokens(packed.text):,}"
        if packed.token_error:
            tokens += f"  {s('exact count failed: ' + packed.token_error, '31')}"
    lines.append(f"  {s('tokens', '2')}    {tokens}")
    if packed.redactions:
        kinds = ", ".join(f"{k}×{n}" for k, n in sorted(packed.redactions.items()))
        total = sum(packed.redactions.values())
        lines.append(f"  {s('redacted', '2')}  {s(f'{total} secret(s)', '33')}: {kinds}")
    if args.top > 0 and files:
        largest = sorted(files, key=lambda f: len(f.content), reverse=True)[: args.top]
        lines.append(f"  {s('largest', '2')}")
        for f in largest:
            approx = f"~{estimate_tokens(f.content):,}"
            lines.append(f"    {approx:>9}  {f.path}")

    if args.dry_run:
        dest = "nothing written (dry run)"
    else:
        dest = " + ".join(filter(None, [
            str(output) if output else "",
            "clipboard" if args.copy else "",
            "stdout" if to_stdout else "",
        ]))
    lines.append(f"  {s('output', '2')}    {dest}")
    print("\n".join(lines), file=sys.stderr)
