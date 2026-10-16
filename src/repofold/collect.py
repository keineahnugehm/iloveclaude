"""Find the files of a project that belong in an LLM prompt."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Never useful in a prompt: dependency trees, build output, lockfiles, media.
DEFAULT_EXCLUDES = [
    ".git/*", "*/.git/*",
    "node_modules/*", "*/node_modules/*",
    "__pycache__/*", "*/__pycache__/*",
    ".venv/*", "*/.venv/*", "venv/*",
    "dist/*", "build/*", "target/*", ".next/*", ".nuxt/*", "coverage/*",
    ".idea/*", ".vscode/*", ".DS_Store", "*/.DS_Store",
    "package-lock.json", "*/package-lock.json",
    "yarn.lock", "*/yarn.lock", "pnpm-lock.yaml", "*/pnpm-lock.yaml",
    "bun.lockb", "Cargo.lock", "poetry.lock", "uv.lock", "composer.lock",
    "Gemfile.lock", "go.sum",
    "*.min.js", "*.min.css", "*.map",
    "*.pyc", "*.pyo", "*.class", "*.o", "*.so", "*.dll", "*.exe",
]

# Files that usually hold credentials. Example/template variants are kept.
_SECRET_FILE_RE = re.compile(
    r"(^\.env(\..+)?$|\.pem$|\.key$|\.p12$|\.pfx$|^id_(rsa|dsa|ecdsa|ed25519)$|^\.npmrc$|^\.pypirc$)"
)
_SECRET_FILE_OK_RE = re.compile(r"\.(example|sample|template|dist)$")

BINARY_SNIFF_BYTES = 8192


@dataclass
class FileEntry:
    path: str  # POSIX path relative to the project root
    content: str


@dataclass
class Collection:
    root: Path
    files: list[FileEntry] = field(default_factory=list)
    skipped_binary: list[str] = field(default_factory=list)
    skipped_large: list[str] = field(default_factory=list)
    skipped_secret_files: list[str] = field(default_factory=list)
    used_git: bool = False


def is_secret_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return bool(_SECRET_FILE_RE.search(name)) and not _SECRET_FILE_OK_RE.search(name)


def matches_any(path: str, patterns: list[str]) -> bool:
    """fnmatch against the full relative path; ``*`` also crosses ``/``."""
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(name, p) for p in patterns)


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:BINARY_SNIFF_BYTES]


# --- .gitignore handling ------------------------------------------------------


def _translate_gitignore(pattern: str) -> str:
    """Translate one gitignore pattern (already stripped of ``!`` and trailing ``/``)."""
    anchored = "/" in pattern
    pattern = pattern.lstrip("/")
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(r"\[")
            else:
                inner = pattern[i + 1:end]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                out.append("[" + inner + "]")
                i = end
        elif c == "\\" and i + 1 < len(pattern):
            i += 1
            out.append(re.escape(pattern[i]))
        else:
            out.append(re.escape(c))
        i += 1
    body = "".join(out)
    return "^" + body + "$" if anchored else "^(?:.*/)?" + body + "$"


@dataclass
class _Rule:
    base: str  # directory of the .gitignore, "" for the root
    regex: re.Pattern
    negate: bool
    dir_only: bool


def _parse_gitignore(text: str, base: str) -> list[_Rule]:
    rules = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        if not line.endswith("\\ "):
            line = line.rstrip()
        negate = line.startswith("!")
        if negate or line.startswith(("\\!", "\\#")):
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line:
            continue
        rules.append(_Rule(base, re.compile(_translate_gitignore(line)), negate, dir_only))
    return rules


def _ignored(rel: str, is_dir: bool, rules: list[_Rule]) -> bool:
    ignored = False
    for rule in rules:
        if rule.dir_only and not is_dir:
            continue
        if rule.base:
            if not rel.startswith(rule.base + "/"):
                continue
            target = rel[len(rule.base) + 1:]
        else:
            target = rel
        if rule.regex.match(target):
            ignored = not rule.negate
    return ignored


def _walk_with_gitignore(root: Path) -> list[str]:
    """Fallback for directories that are not git work trees."""
    found: list[str] = []
    rules_at: dict[str, list[_Rule]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        parent = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
        rules = list(rules_at.get(parent, [])) if rel_dir else []
        gi = Path(dirpath) / ".gitignore"
        if gi.is_file():
            rules += _parse_gitignore(gi.read_text(encoding="utf-8", errors="replace"), rel_dir)
        rules_at[rel_dir] = rules

        def rel(name: str, rel_dir: str = rel_dir) -> str:
            return f"{rel_dir}/{name}" if rel_dir else name

        dirnames[:] = sorted(
            d for d in dirnames
            if d != ".git"
            and not os.path.islink(os.path.join(dirpath, d))
            and not _ignored(rel(d), True, rules)
        )
        for name in sorted(filenames):
            if not _ignored(rel(name), False, rules):
                found.append(rel(name))
    return found


def _git_ls_files(root: Path) -> list[str] | None:
    """Tracked + untracked-but-not-ignored files, exactly as git sees them."""
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root, capture_output=True, text=True, check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", "ls-files", "-z",
             "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = {p for p in out.stdout.decode("utf-8", "replace").split("\0") if p}
    return sorted(paths)


# --- public API ---------------------------------------------------------------


def collect(
    root: str | os.PathLike,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    use_default_excludes: bool = True,
    respect_gitignore: bool = True,
    use_git: bool = True,
    max_file_bytes: int = 1_000_000,
    skip_paths: set[Path] | None = None,
) -> Collection:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    result = Collection(root=root)
    candidates = None
    if respect_gitignore and use_git:
        candidates = _git_ls_files(root)
        result.used_git = candidates is not None
    if candidates is None:
        if respect_gitignore:
            candidates = _walk_with_gitignore(root)
        else:
            candidates = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d != ".git")
                for name in sorted(filenames):
                    candidates.append((Path(dirpath) / name).relative_to(root).as_posix())

    excludes = (DEFAULT_EXCLUDES if use_default_excludes else []) + (exclude or [])
    skip = {p.resolve() for p in (skip_paths or set())}

    for rel in candidates:
        full = root / rel
        if full.is_symlink() or not full.is_file() or full.resolve() in skip:
            continue
        if include and not matches_any(rel, include):
            continue
        if matches_any(rel, excludes):
            continue
        if use_default_excludes and is_secret_file(rel):
            result.skipped_secret_files.append(rel)
            continue
        if full.stat().st_size > max_file_bytes:
            result.skipped_large.append(rel)
            continue
        data = full.read_bytes()
        if is_binary(data):
            result.skipped_binary.append(rel)
            continue
        text = data.decode("utf-8", errors="replace")
        text = text.removeprefix("\ufeff")
        result.files.append(FileEntry(rel, text.replace("\r\n", "\n")))
    return result
