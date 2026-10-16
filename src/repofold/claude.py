"""Exact token counts from the Anthropic API (optional: ``pip install 'repofold[claude]'``)."""

from __future__ import annotations

DEFAULT_MODEL = "claude-opus-5-5"


class TokenCountError(Exception):
    pass


def count_tokens(text: str, model: str = DEFAULT_MODEL) -> int:
    """Return the input tokens ``text`` uses as one user message for ``model``.

    This sends ``text`` to the Anthropic API. Credentials come from the
    environment (``ANTHROPIC_API_KEY``) or an ``ant auth login`` profile.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise TokenCountError(
            "exact counts need the Anthropic SDK: pip install 'repofold[claude]'"
        ) from exc

    try:
        client = anthropic.Anthropic()
        response = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.AuthenticationError as exc:
        raise TokenCountError(
            "Anthropic rejected the credentials: set ANTHROPIC_API_KEY or run `ant auth login`"
        ) from exc
    except TypeError as exc:
        # The SDK raises a bare TypeError when no credentials are configured at all.
        if "authentication" not in str(exc).lower():
            raise
        raise TokenCountError(
            "no Anthropic credentials found: set ANTHROPIC_API_KEY or run `ant auth login`"
        ) from exc
    except anthropic.NotFoundError as exc:
        raise TokenCountError(f"unknown model {model!r}") from exc
    except anthropic.APIConnectionError as exc:
        raise TokenCountError("could not reach the Anthropic API") from exc
    except anthropic.APIStatusError as exc:
        raise TokenCountError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.AnthropicError as exc:
        raise TokenCountError(str(exc)) from exc
    return response.input_tokens
