import shutil
import subprocess
import sys
import types

import pytest

import repofold.cli
from repofold import collect, redact, render_markdown, render_tree, render_xml
from repofold.cli import apply_budget, main, parse_size
from repofold.collect import FileEntry, _ignored, _parse_gitignore
from repofold.watch import watch


def write(root, rel, content="x\n"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def paths(result):
    return [f.path for f in result.files]


# --- gitignore fallback --------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path", "is_dir", "expected"),
    [
        ("*.log", "a.log", False, True),
        ("*.log", "deep/dir/a.log", False, True),
        ("/build", "build", True, True),
        ("/build", "src/build", True, False),
        ("build/", "build", False, False),
        ("build/", "src/build", True, True),
        ("docs/*.md", "docs/a.md", False, True),
        ("docs/*.md", "docs/sub/a.md", False, False),
        ("**/temp", "a/b/temp", True, True),
        ("a/**/b", "a/x/y/b", False, True),
        ("a/**/b", "a/b", False, True),
        ("logs/**", "logs/x/y.txt", False, True),
        ("file?.txt", "file1.txt", False, True),
        ("file[0-9].txt", "fileA.txt", False, False),
    ],
)
def test_gitignore_patterns(pattern, path, is_dir, expected):
    assert _ignored(path, is_dir, _parse_gitignore(pattern, "")) is expected


def test_gitignore_negation_and_comments():
    rules = _parse_gitignore("# comment\n*.log\n!keep.log\n\n", "")
    assert _ignored("x.log", False, rules)
    assert not _ignored("keep.log", False, rules)


def test_walk_respects_nested_gitignore(tmp_path):
    write(tmp_path, ".gitignore", "*.log\nsecret_dir/\n")
    write(tmp_path, "app.py")
    write(tmp_path, "debug.log")
    write(tmp_path, "secret_dir/x.py")
    write(tmp_path, "pkg/.gitignore", "generated.py\n")
    write(tmp_path, "pkg/generated.py")
    write(tmp_path, "pkg/real.py")
    write(tmp_path, "generated.py")  # only ignored inside pkg/

    result = collect(tmp_path, use_git=False)
    assert paths(result) == [".gitignore", "app.py", "generated.py", "pkg/.gitignore", "pkg/real.py"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_uses_git_when_available(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write(tmp_path, ".gitignore", "ignored.txt\n")
    write(tmp_path, "ignored.txt")
    write(tmp_path, "kept.txt")

    result = collect(tmp_path)
    assert result.used_git
    assert paths(result) == [".gitignore", "kept.txt"]


# --- filtering ------------------------------------------------------------------


def test_default_excludes_binary_large_and_credentials(tmp_path):
    write(tmp_path, "main.py", "print('hi')\n")
    write(tmp_path, "node_modules/lib/index.js")
    write(tmp_path, "package-lock.json", "{}")
    write(tmp_path, "logo.png", b"\x89PNG\r\n\x1a\n\0\0\0")
    write(tmp_path, "big.txt", "a" * 2000)
    write(tmp_path, ".env", "TOKEN=abc\n")
    write(tmp_path, ".env.example", "TOKEN=\n")

    result = collect(tmp_path, use_git=False, max_file_bytes=1000)
    assert paths(result) == [".env.example", "main.py"]
    assert result.skipped_binary == ["logo.png"]
    assert result.skipped_large == ["big.txt"]
    assert result.skipped_secret_files == [".env"]


def test_include_and_exclude_globs(tmp_path):
    write(tmp_path, "src/a.py")
    write(tmp_path, "src/b.js")
    write(tmp_path, "tests/test_a.py")

    result = collect(tmp_path, use_git=False, include=["*.py"], exclude=["tests/*"])
    assert paths(result) == ["src/a.py"]


def test_crlf_and_bom_are_normalised(tmp_path):
    write(tmp_path, "win.txt", b"\xef\xbb\xbfline1\r\nline2\r\n")
    assert collect(tmp_path, use_git=False).files[0].content == "line1\nline2\n"


# --- redaction ------------------------------------------------------------------


def test_redacts_common_secrets():
    # Built at runtime so the test file itself never contains a real-looking token.
    github = "ghp_" + "A1b2C3d4" * 5
    aws = "AKIA" + "QWERTYUIOPASDFGH"
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
    text = f"token = '{github}'\naws = {aws}\n{key}\nplain = 'hello'\n"

    out, counts = redact(text)
    assert github not in out and aws not in out and "MIIEow" not in out
    assert "plain = 'hello'" in out
    assert counts == {"github-token": 1, "aws-access-key": 1, "private-key": 1}


def test_redact_leaves_normal_code_alone():
    code = "def sk_live_test():\n    return 'sk-short'\n"
    assert redact(code) == (code, {})


# --- rendering ------------------------------------------------------------------


def test_tree_rendering():
    assert render_tree(["b.py", "src/a.py", "src/util/x.py", "README.md"]) == (
        "├── src/\n"
        "│   ├── util/\n"
        "│   │   └── x.py\n"
        "│   └── a.py\n"
        "├── b.py\n"
        "└── README.md"
    )


def test_markdown_fence_survives_backticks_in_content():
    files = [FileEntry("README.md", "```python\nprint(1)\n```\n")]
    out = render_markdown("demo", files)
    assert "````markdown\n```python" in out
    assert out.rstrip().endswith("````")


def test_tree_only_header_has_no_token_count():
    files = [FileEntry("a.py", "x = 1\n")]
    assert "1 file · packed with repofold" in render_markdown("demo", files, tree_only=True)
    assert "approx_tokens" not in render_xml("demo", files, tree_only=True)
    assert "1 file · ~2 tokens" in render_markdown("demo", files)


def test_xml_output_escapes_attributes():
    out = render_xml("demo", [FileEntry('we"ird.py', "x = 1\n")])
    assert '<file path="we&quot;ird.py">\nx = 1\n</file>' in out
    assert out.startswith('<repository name="demo" files="1"')


# --- cli ------------------------------------------------------------------------


def test_parse_size():
    assert parse_size("500") == 500
    assert parse_size("100k") == 100_000
    assert parse_size("1.5m") == 1_500_000


def test_budget_keeps_files_that_fit():
    files = [FileEntry("a", "x" * 400), FileEntry("b", "x" * 4000), FileEntry("c", "x" * 40)]
    kept, dropped = apply_budget(files, 200)
    assert [f.path for f in kept] == ["a", "c"]
    assert dropped == ["b"]


def test_cli_writes_output_file(tmp_path, capsys):
    write(tmp_path, "hello.py", "print('hello')\n")
    out = tmp_path / "packed.xml"

    assert main([str(tmp_path), "-o", str(out), "-f", "xml"]) == 0
    text = out.read_text(encoding="utf-8")
    assert '<file path="hello.py">' in text
    assert "1 included" in capsys.readouterr().err

    # Running again must not pack its own previous output.
    assert main([str(tmp_path), "-o", str(out), "-f", "xml", "-q"]) == 0
    assert "packed.xml" not in out.read_text(encoding="utf-8")


def test_cli_stdout_and_dry_run(tmp_path, capsys):
    write(tmp_path, "a.py", "a = 1\n")
    assert main([str(tmp_path), "--stdout", "-q"]) == 0
    assert "### a.py" in capsys.readouterr().out

    assert main([str(tmp_path), "-n"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "dry run" in captured.err


def test_cli_rejects_missing_directory(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_cli_rejects_non_positive_interval(tmp_path, capsys):
    assert main([str(tmp_path), "-n", "--interval", "0"]) == 2
    assert "--interval" in capsys.readouterr().err


# --- exact token counts ----------------------------------------------------------


def install_fake_anthropic(monkeypatch, *, tokens=4321, error=None):
    """Stand-in for the SDK so tests need neither the package nor an API key."""
    mod = types.ModuleType("anthropic")

    class AnthropicError(Exception):
        pass

    class APIConnectionError(AnthropicError):
        pass

    class APIStatusError(AnthropicError):
        def __init__(self, message, status_code=500):
            super().__init__(message)
            self.message = message
            self.status_code = status_code

    class AuthenticationError(APIStatusError):
        pass

    class NotFoundError(APIStatusError):
        pass

    calls = []

    class Messages:
        def count_tokens(self, **kwargs):
            calls.append(kwargs)
            if error == "missing-credentials":
                # What the real SDK raises when no key or profile is configured.
                raise TypeError('"Could not resolve authentication method. Expected one of '
                                'api_key, auth_token, or credentials to be set."')
            if error:
                raise getattr(mod, error)("boom")
            return types.SimpleNamespace(input_tokens=tokens)

    class Anthropic:
        def __init__(self):
            self.messages = Messages()

    for cls in (AnthropicError, APIConnectionError, APIStatusError, AuthenticationError,
                NotFoundError, Anthropic):
        setattr(mod, cls.__name__, cls)
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return calls


def test_exact_token_count(tmp_path, monkeypatch, capsys):
    calls = install_fake_anthropic(monkeypatch, tokens=4321)
    write(tmp_path, "app.py", "print('hi')\n")

    assert main([str(tmp_path), "-n", "--exact"]) == 0
    assert "4,321 (exact, claude-opus-5-5)" in capsys.readouterr().err
    assert calls[0]["model"] == "claude-opus-5-5"
    assert "print('hi')" in calls[0]["messages"][0]["content"]


def test_exact_token_count_with_bad_credentials(tmp_path, monkeypatch, capsys):
    install_fake_anthropic(monkeypatch, error="AuthenticationError")
    write(tmp_path, "app.py")

    assert main([str(tmp_path), "-n", "--exact", "--model", "claude-sonnet-5-5"]) == 1
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err
    assert "~" in err  # falls back to the estimate


def test_exact_token_count_without_credentials(tmp_path, monkeypatch, capsys):
    install_fake_anthropic(monkeypatch, error="missing-credentials")
    write(tmp_path, "app.py")

    assert main([str(tmp_path), "-n", "--exact"]) == 1
    assert "no Anthropic credentials found" in capsys.readouterr().err


def test_exact_token_count_without_sdk(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` fail
    write(tmp_path, "app.py")

    assert main([str(tmp_path), "-n", "-q", "--exact"]) == 1
    assert "pip install 'repofold[claude]'" in capsys.readouterr().err


# --- watch mode -----------------------------------------------------------------


def test_watch_reacts_to_changes(tmp_path):
    target = write(tmp_path, "a.py", "a = 1\n")
    changes, sleeps = [], []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            target.write_text("a = 1\nb = 2\n", encoding="utf-8")

    watch(tmp_path, lambda: changes.append(1), sleep=fake_sleep, max_polls=3)
    assert changes == [1]


def test_watch_ignores_output_file_and_git_dir(tmp_path):
    out = tmp_path / "packed.md"
    write(tmp_path, "a.py")
    changes, counter = [], [0]

    def fake_sleep(seconds):
        counter[0] += 1
        write(tmp_path, "packed.md", "x" * counter[0])
        write(tmp_path, ".git/index", "y" * counter[0])

    watch(tmp_path, lambda: changes.append(1), ignore=[out], sleep=fake_sleep, max_polls=3)
    assert changes == []


def test_cli_watch_repacks_on_change(tmp_path, monkeypatch, capsys):
    write(tmp_path, "a.py", "a = 1\n")
    out = tmp_path / "packed.md"
    seen = {}

    def fake_watch(root, on_change, *, interval, ignore):
        seen["ignore"] = ignore
        write(tmp_path, "b.py", "b = 2\n")
        on_change()
        raise KeyboardInterrupt

    monkeypatch.setattr(repofold.cli, "watch", fake_watch)
    assert main([str(tmp_path), "-o", str(out), "--watch"]) == 0
    assert seen["ignore"] == [out]
    assert "### b.py" in out.read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert "watching" in err and "change detected" in err
