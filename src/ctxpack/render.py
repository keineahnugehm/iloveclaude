"""Turn collected files into a single prompt document."""

from __future__ import annotations

import html
import math
import re

from .collect import FileEntry

LANGUAGES = {
    "py": "python", "pyi": "python", "js": "javascript", "mjs": "javascript",
    "cjs": "javascript", "jsx": "jsx", "ts": "typescript", "tsx": "tsx",
    "rs": "rust", "go": "go", "java": "java", "kt": "kotlin", "kts": "kotlin",
    "swift": "swift", "c": "c", "h": "c", "cc": "cpp", "cpp": "cpp", "hpp": "cpp",
    "cs": "csharp", "rb": "ruby", "php": "php", "scala": "scala", "lua": "lua",
    "sh": "bash", "bash": "bash", "zsh": "bash", "fish": "fish", "ps1": "powershell",
    "sql": "sql", "html": "html", "htm": "html", "css": "css", "scss": "scss",
    "vue": "vue", "svelte": "svelte", "json": "json", "yaml": "yaml", "yml": "yaml",
    "toml": "toml", "ini": "ini", "xml": "xml", "md": "markdown", "mdx": "mdx",
    "dart": "dart", "ex": "elixir", "exs": "elixir", "erl": "erlang", "hs": "haskell",
    "ml": "ocaml", "clj": "clojure", "r": "r", "jl": "julia", "zig": "zig",
    "nix": "nix", "tf": "hcl", "proto": "protobuf", "graphql": "graphql",
}
SPECIAL_NAMES = {"Dockerfile": "dockerfile", "Makefile": "makefile", "CMakeLists.txt": "cmake"}


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token for code and English)."""
    return math.ceil(len(text) / 4)


def language_for(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name in SPECIAL_NAMES:
        return SPECIAL_NAMES[name]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return LANGUAGES.get(ext, "")


def render_tree(paths: list[str]) -> str:
    tree: dict = {}
    for path in paths:
        node = tree
        for part in path.split("/"):
            node = node.setdefault(part, {})

    lines: list[str] = []

    def walk(node: dict, prefix: str) -> None:
        # Directories first, then files, each alphabetically.
        items = sorted(node.items(), key=lambda kv: (not kv[1], kv[0].lower()))
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if child else ''}")
            walk(child, prefix + ("    " if last else "│   "))

    walk(tree, "")
    return "\n".join(lines)


def _fence(content: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def render_markdown(name: str, files: list[FileEntry], *, tree_only: bool = False) -> str:
    paths = [f.path for f in files]
    total = sum(estimate_tokens(f.content) for f in files)
    out = [
        f"# {name}",
        "",
        f"{len(files)} files · ~{total:,} tokens · packed with ctxpack",
        "",
        "## Directory structure",
        "",
        "```",
        render_tree(paths),
        "```",
    ]
    if not tree_only:
        out += ["", "## Files"]
        for f in files:
            fence = _fence(f.content)
            body = f.content if f.content.endswith("\n") or not f.content else f.content + "\n"
            out += ["", f"### {f.path}", "", f"{fence}{language_for(f.path)}", body + fence]
    return "\n".join(out) + "\n"


def render_xml(name: str, files: list[FileEntry], *, tree_only: bool = False) -> str:
    paths = [f.path for f in files]
    total = sum(estimate_tokens(f.content) for f in files)
    out = [
        f'<repository name="{html.escape(name)}" files="{len(files)}" approx_tokens="{total}">',
        "<directory_structure>",
        render_tree(paths),
        "</directory_structure>",
    ]
    if not tree_only:
        out.append("<files>")
        for f in files:
            body = f.content if f.content.endswith("\n") or not f.content else f.content + "\n"
            out.append(f'<file path="{html.escape(f.path)}">\n{body}</file>')
        out.append("</files>")
    out.append("</repository>")
    return "\n".join(out) + "\n"


RENDERERS = {"markdown": render_markdown, "xml": render_xml}
