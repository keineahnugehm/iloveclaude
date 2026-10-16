"""Render docs/demo.svg: an animated terminal showing real repofold output.

Run from the repository root:  python scripts/make_demo.py
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
import tempfile
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
cli = importlib.import_module("repofold.cli")

# A small but realistic project, including the kind of mess repofold cleans up.
FAKE_KEY = "sk-ant-api03-" + "dEmO" * 8  # built at runtime; never a real key
SAMPLE = {
    "README.md": "# shop-api\n\nA tiny shop backend.\n",
    "pyproject.toml": '[project]\nname = "shop-api"\nversion = "1.0.0"\n',
    "src/shop/__init__.py": "",
    "src/shop/app.py": (
        "from fastapi import FastAPI\n\nfrom .models import Order\n\n"
        f'CLAUDE_KEY = "{FAKE_KEY}"  # oops\n\napp = FastAPI()\n'
        + '\n\n@app.post("/orders")\ndef create(order: Order) -> Order:\n    return order\n' * 6
    ),
    "src/shop/models.py": "from pydantic import BaseModel\n\n\nclass Order(BaseModel):\n"
                          "    id: int\n    total: float\n" * 4,
    "src/shop/db.py": "import sqlite3\n\n\ndef connect(path: str):\n    return sqlite3.connect(path)\n" * 3,
    "tests/test_app.py": "def test_create():\n    assert True\n" * 3,
    ".env": "DATABASE_URL=postgres://prod\n",
    ".gitignore": "node_modules/\n",
    "package-lock.json": "{}\n",
    "node_modules/left-pad/index.js": "module.exports = 1\n",
    "static/logo.png": b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR",
}

COMMANDS = [
    ["-c"],
    ["-f", "xml", "--tree-only", "--stdout", "-q"],
]

CHAR_W, LINE_H, FONT = 8.1, 19, 13.5
PAD_X, TOP = 18, 46
TYPE_S, LINE_S, PAUSE_S, HOLD_S = 0.055, 0.035, 1.4, 4.0

PALETTE = {
    "bg": "#0d1117", "bar": "#161b22", "fg": "#c9d1d9", "dim": "#8b949e",
    "prompt": "#3fb950", "accent": "#d2a8ff", "warn": "#e3b341",
}


def build_sample(base: Path) -> Path:
    project = base / "shop-api"
    for rel, content in SAMPLE.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return project


def run(args: list[str], cwd: Path) -> list[str]:
    """Run the real CLI and capture what a user would see in the terminal."""
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    os.chdir(cwd)
    try:
        # The summary is real; only the system clipboard tool is stubbed out.
        cli.copy_to_clipboard = lambda text: None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(args)
    finally:
        os.chdir(old)
    return (err.getvalue() + out.getvalue()).rstrip("\n").splitlines()


def style_line(line: str) -> str:
    """Return SVG tspans with a little syntax colouring for the summary."""
    text = escape(line)
    if line.startswith("repofold ·"):
        return f'<tspan fill="{PALETTE["accent"]}" font-weight="700">repofold</tspan>{text[8:]}'
    for label in ("files", "tokens", "redacted", "largest", "output"):
        if line.startswith(f"  {label}"):
            rest = escape(line[2 + len(label):])
            if label == "redacted":
                head, _, tail = rest.partition(":")
                rest = f'<tspan fill="{PALETTE["warn"]}">{head}</tspan>:{tail}'
            return f'  <tspan fill="{PALETTE["dim"]}">{label}</tspan>{rest}'
    return text


def visible_between(start: float, end: float | None, total: float) -> str:
    """SMIL animation that shows an element from ``start`` to ``end`` on every loop."""
    if end is None:
        values, times = "0;1", f"0;{start / total:.4f}"
    else:
        values, times = "0;1;0", f"0;{start / total:.4f};{end / total:.4f}"
    return (f'<animate attributeName="opacity" values="{values}" keyTimes="{times}" '
            f'calcMode="discrete" dur="{total:.2f}s" repeatCount="indefinite"/>')


def render(sessions: list[tuple[str, list[str]]]) -> str:
    # Lay out the timeline first: (markup, row, visible_from, visible_until).
    frames: list[tuple[str, int, float, float | None]] = []
    row, t = 0, 0.6
    for command, output in sessions:
        typed = f"repofold {command}".rstrip()
        for i in range(1, len(typed) + 1):
            end = t + TYPE_S if i < len(typed) else None
            frames.append((_prompt(typed[:i]), row, t, end))
            t += TYPE_S
        t += 0.35
        for line in output:
            row += 1
            frames.append((style_line(line), row, t, None))
            t += LINE_S
        row += 2
        t += PAUSE_S
    total = t + HOLD_S

    width = int(PAD_X * 2 + CHAR_W * max(
        [len(f"$ repofold {c}") for c, _ in sessions] + [len(x) for _, o in sessions for x in o]
    ))
    height = TOP + LINE_H * (row - 1) + 14
    rows = []
    for markup, r, start, end in frames:
        y = TOP + r * LINE_H
        rows.append(f'<text x="{PAD_X}" y="{y}" opacity="0" xml:space="preserve">'
                    f'{markup}{visible_between(start, end, total)}</text>')

    dots = "".join(
        f'<circle cx="{20 + i * 18}" cy="16" r="5.5" fill="{c}"/>'
        for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f"))
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}" role="img" aria-label="repofold packing a project in the terminal">
<title>repofold demo</title>
<rect width="{width}" height="{height}" rx="10" fill="{PALETTE["bg"]}"/>
<rect width="{width}" height="32" rx="10" fill="{PALETTE["bar"]}"/>
<rect y="22" width="{width}" height="10" fill="{PALETTE["bar"]}"/>
{dots}
<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace" \
font-size="{FONT}" fill="{PALETTE["fg"]}">
{chr(10).join(rows)}
</g>
</svg>
'''


def _prompt(typed: str) -> str:
    return f'<tspan fill="{PALETTE["prompt"]}">$</tspan> {escape(typed)}'


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = build_sample(Path(tmp))
        sessions = [(" ".join(args), run(args, project)) for args in COMMANDS]
    svg = render(sessions)
    target = ROOT / "docs" / "demo.svg"
    target.parent.mkdir(exist_ok=True)
    target.write_text(svg, encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({len(svg):,} bytes)")


if __name__ == "__main__":
    main()
