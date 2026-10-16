"""Re-pack whenever files change. Polls file stats, so it needs no dependencies."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path

# Directories whose churn never changes the packed output.
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".next", ".nuxt",
}

SETTLE_SECONDS = 0.2


def _key(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(path))


def snapshot(root: str | os.PathLike, ignore: set[str] = frozenset()) -> dict[str, tuple[int, int]]:
    """Map every file under ``root`` to its (mtime_ns, size)."""
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            key = _key(full)
            if key in ignore:
                continue
            try:
                st = os.stat(full)
            except OSError:  # deleted between listing and stat
                continue
            state[key] = (st.st_mtime_ns, st.st_size)
    return state


def watch(
    root: str | os.PathLike,
    on_change: Callable[[], object],
    *,
    interval: float = 1.0,
    ignore: Iterable[str | os.PathLike] = (),
    sleep: Callable[[float], None] = time.sleep,
    max_polls: int | None = None,
) -> None:
    """Call ``on_change`` after files under ``root`` change. Runs until interrupted."""
    root = Path(root).resolve()
    ignored = {_key(p) for p in ignore}
    before = snapshot(root, ignored)
    polls = 0
    while max_polls is None or polls < max_polls:
        polls += 1
        sleep(interval)
        after = snapshot(root, ignored)
        if after == before:
            continue
        # Editors often save in several steps; let them finish before re-packing.
        sleep(SETTLE_SECONDS)
        before = snapshot(root, ignored)
        on_change()
