"""repofold: pack a codebase into one LLM-ready prompt."""

from .collect import Collection, FileEntry, collect
from .redact import redact
from .render import estimate_tokens, render_markdown, render_tree, render_xml

__version__ = "0.1.0"

__all__ = [
    "Collection",
    "FileEntry",
    "__version__",
    "collect",
    "estimate_tokens",
    "redact",
    "render_markdown",
    "render_tree",
    "render_xml",
]
