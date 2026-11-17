"""A small declarative validation framework built on pandas.

A ``Rule`` is a vectorised predicate that returns a boolean Series marking the
rows that *violate* it. Rules have a severity:

* ``error``   - the row is rejected and written to ``etl.row_issues`` with the
                list of every rule it broke, so it can be fixed and replayed.
* ``warning`` - the row is loaded but flagged (``is_flagged``) and recorded.

Keeping rules as data (name, description, column, severity) means the UI and
the database can explain *why* a row was rejected, not just that it was.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

Severity = Literal["error", "warning"]
Check = Callable[[pd.DataFrame, dict[str, Any]], pd.Series]


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    check: Check
    severity: Severity = "error"
    column: str | None = None


@dataclass
class RuleOutcome:
    rule: Rule
    rows_checked: int
    rows_failed: int

    def as_record(self, dataset: str) -> dict:
        return {
            "dataset": dataset, "rule_name": self.rule.name, "description": self.rule.description,
            "severity": self.rule.severity, "column_name": self.rule.column,
            "rows_checked": self.rows_checked, "rows_failed": self.rows_failed,
        }


@dataclass
class ValidationResult:
    dataset: str
    valid: pd.DataFrame                     # rows to load (includes warned rows, flagged)
    rejected: pd.DataFrame                  # rows with >=1 error; column "_reasons"
    warned: pd.DataFrame                    # loaded rows with >=1 warning; column "_reasons"
    outcomes: list[RuleOutcome] = field(default_factory=list)

    @property
    def rule_records(self) -> list[dict]:
        return [o.as_record(self.dataset) for o in self.outcomes]


def _reasons(fail_matrix: pd.DataFrame) -> pd.Series:
    """Turn a boolean (rows x rules) matrix into a list of failed rule names per row."""
    if fail_matrix.empty:
        return pd.Series([[] for _ in range(len(fail_matrix))], index=fail_matrix.index, dtype=object)
    names = fail_matrix.columns.to_numpy()
    return pd.Series([list(names[row]) for row in fail_matrix.to_numpy()], index=fail_matrix.index, dtype=object)


def run_rules(df: pd.DataFrame, rules: list[Rule], dataset: str,
              context: dict[str, Any] | None = None) -> ValidationResult:
    context = context or {}
    errors, warnings, outcomes = {}, {}, []
    for rule in rules:
        mask = rule.check(df, context).reindex(df.index).fillna(False).astype(bool)
        outcomes.append(RuleOutcome(rule, len(df), int(mask.sum())))
        (errors if rule.severity == "error" else warnings)[rule.name] = mask

    err = pd.DataFrame(errors, index=df.index, dtype=bool)
    warn = pd.DataFrame(warnings, index=df.index, dtype=bool)
    is_rejected = err.any(axis=1) if not err.empty else pd.Series(False, index=df.index)
    is_warned = (warn.any(axis=1) if not warn.empty else pd.Series(False, index=df.index)) & ~is_rejected

    rejected = df[is_rejected].copy()
    rejected["_reasons"] = _reasons(err[is_rejected])
    warned = df[is_warned].copy()
    warned["_reasons"] = _reasons(warn[is_warned])
    valid = df[~is_rejected].copy()
    valid["_flagged"] = is_warned[~is_rejected]
    return ValidationResult(dataset, valid, rejected, warned, outcomes)
