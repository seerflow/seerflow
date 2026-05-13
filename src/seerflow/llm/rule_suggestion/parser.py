r"""Pure YAML extractor for LLM-drafted Sigma rule completions (S-100).

The LLM is asked to emit a single fenced YAML block (``\`\`\`yaml ... \`\`\```).
Reality is more forgiving — some completions wrap the block in commentary,
some drop the language label, some omit the fence entirely. This module
extracts a single YAML body from any of those shapes without raising.

The validation verdict (``ok`` / ``yaml`` / ``schema`` / ``compile``) is
produced by the service via :func:`seerflow.sigma.validator.validate_yaml`;
the parser is intentionally permissive so a "no fence" completion still
gets a chance through the validator.
"""

from __future__ import annotations

import re

# Match the first fenced code block. Accepts ``yaml``, ``yml``, or no
# language tag at all. Uses ``re.DOTALL`` so the body can span newlines.
# ``?:`` is used to avoid capturing the lang tag — the only capture group
# is the body itself.
_FENCE_RE = re.compile(
    r"```(?:yaml|yml)?[ \t]*\n(.+?)\n```",
    re.IGNORECASE | re.DOTALL,
)


def extract_yaml(completion: str) -> str:
    """Return a candidate YAML body from ``completion``.

    Strategy:

    1. If a fenced block (```` ```yaml ```` / ```` ```yml ```` / ```` ``` ````)
       is present, return the body of the **first** fence — stripped of
       leading/trailing whitespace.
    2. If no closed fence is found, return the stripped whole text.

    The function never raises. An empty or whitespace-only input maps to
    the empty string; the validator will then emit a ``"yaml"``-stage
    failure when the service drives it through.
    """
    if not completion or not completion.strip():
        return ""

    match = _FENCE_RE.search(completion)
    if match is not None:
        return match.group(1).strip()

    return completion.strip()
