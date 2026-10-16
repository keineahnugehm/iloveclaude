"""Command-line interface for ctxpack."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .collect import collect
from .redact import redact
from .render import RENDERERS, estimate_tokens

EXTENSIONS = {"markdown": "md", "xml": "xml"}


def parse_size(value: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?)b?\s*", value.lower())
    if not m:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r} (try 500k or 2m)")
    factor = {"": 1, "k": 1_000, "m": 1_000_000, "g": 1_000_000_000}[m.group(2)]
    return int(float(m.group(1)) * factor)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctxpack",
        description="Pack a codebase into a single LLM-ready prompt.",
        epilog="examples:\n"
               "  ctxpack                      pack the current directory\n"
               "  ctxpack -c                   ...and copy it to the clipboard\n"
               "  ctxpack src -i '*.py'        only Python files under src/\n"
               "  ctxpack --max-tokens 100k    stay inside a token budget\n"
               "  ctxpack -n                   just show what would be packed",
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
    p.add_argument("--top", type=int, default=5, metavar="N",
                   help="list the N largest files in the summary (default: 5)")
    p.add_argument("--no-gitignore", action="store_true", help="ignore .gitignore rules")
    p.add_argument("--no-default-excludes", action="store_true",
                   help="also pack lockfiles, build output and credential files")
    p.add_argument("--no-redact", action="store_true", help="don't redact detected secrets")
    p.add_argument("-q", "--quiet", action="store_true", help="no summary on stderr")
    p.add_argument("-V", "--version", action="version", version=f"ctxpack {__version__}")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        print(f"ctxpack: not a directory: {root}", file=sys.stderr)
        return 2

    to_stdout = args.stdout or (not args.output and not args.copy and not sys.stdout.isatty())
    output = Path(args.output) if args.output else None
    if not output and not args.copy and not to_stdout and not args.dry_run:
        output = Path(f"ctxpack-output.{EXTENSIONS[args.format]}")

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

    if not args.dry_run:
        if output:
            with open(output, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        if args.copy:
            try:
                copy_to_clipboard(text)
            except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
                print(f"ctxpack: could not copy to clipboard: {exc}", file=sys.stderr)
                return 1
        if to_stdout:
            # Pipes on Windows default to a legacy code page that can't encode the tree.
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
            sys.stdout.write(text)

    if not args.quiet:
        _print_summary(args, name, result, files, dropped, redactions, text, output, to_stdout)
    return 0


def _print_summary(args, name, result, files, dropped, redactions, text, output, to_stdout):
    s = _Style(sys.stderr)
    lines = [f"{s('ctxpack', '1')} · {name}"]

    skipped = []
    if result.skipped_binary:
        skipped.append(f"{len(result.skipped_binary)} binary")
    if result.skipped_large:
        skipped.append(f"{len(result.skipped_large)} too large")
    if result.skipped_secret_files:
        skipped.append(f"{len(result.skipped_secret_files)} credential files")
    if dropped:
        skipped.append(f"{len(dropped)} over budget")
    detail = f" ({', '.join(skipped)} skipped)" if skipped else ""
    lines.append(f"  {s('files', '2')}     {len(files)} included{detail}")

    lines.append(f"  {s('tokens', '2')}    ~{estimate_tokens(text):,}")
    if redactions:
        kinds = ", ".join(f"{k}×{n}" for k, n in sorted(redactions.items()))
        total = sum(redactions.values())
        lines.append(f"  {s('redacted', '2')}  {s(f'{total} secret(s)', '33')}: {kinds}")
    if args.top > 0 and files:
        largest = sorted(files, key=lambda f: len(f.content), reverse=True)[: args.top]
        lines.append(f"  {s('largest', '2')}")
        for f in largest:
            lines.append(f"    ~{estimate_tokens(f.content):>8,}  {f.path}")

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
