"""Layered Sigma YAML validation with structured error reporting.

Three failure stages:

* ``yaml``    — YAML syntax / parse error (carries line, column from problem_mark)
* ``schema``  — pySigma schema violation (missing required fields, bad types)
* ``compile`` — pipeline / compilation error (no line info, message only)
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml
from sigma.exceptions import SigmaError
from sigma.rule import SigmaRule

from seerflow.sigma.matcher import compile_rule
from seerflow.sigma.pipeline import seerflow_pipeline


@dataclass(frozen=True)
class SigmaRuleValidationError(Exception):
    """Structured error from Sigma YAML validation."""

    stage: str  # "yaml" | "schema" | "compile"
    message: str
    line: int | None = None
    column: int | None = None
    field: str | None = None

    def __str__(self) -> str:
        loc = ""
        if self.line is not None:
            loc = f" (line {self.line}"
            if self.column is not None:
                loc += f", col {self.column}"
            loc += ")"
        return f"[{self.stage}]{loc} {self.message}"


def validate_yaml(text: str) -> SigmaRule:
    """Parse + compile *text*; raise ``SigmaRuleValidationError`` on failure.

    On success returns the ``SigmaRule`` with the seerflow pipeline applied.
    Caller is responsible for indexing/persistence.
    """
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise SigmaRuleValidationError(
            stage="yaml",
            message=str(exc),
            line=(mark.line + 1) if mark is not None else None,
            column=(mark.column + 1) if mark is not None else None,
        ) from exc

    try:
        rule = SigmaRule.from_yaml(text)
    except SigmaError as exc:
        raise SigmaRuleValidationError(stage="schema", message=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - pySigma raises various types
        raise SigmaRuleValidationError(stage="schema", message=str(exc)) from exc

    try:
        seerflow_pipeline().apply(rule)
        compile_rule(rule)
    except Exception as exc:  # noqa: BLE001 - compile failure surfaces from many places
        raise SigmaRuleValidationError(stage="compile", message=str(exc)) from exc

    return rule
