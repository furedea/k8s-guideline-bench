"""Atomic and adopted constraints derived from normative guideline text."""

import enum
import json
from pathlib import Path
from typing import Any

import base
import error
import pydantic


class Judgeability(enum.StrEnum):
    """Expected judgeability of an atomic constraint."""

    MACHINE_CHECKABLE = "machine_checkable"
    LLM_CHECKABLE = "llm_checkable"
    HYBRID = "hybrid"


class AtomicConstraint(base.FrozenModel):
    """Atomic constraint derived from normative statements."""

    id: str
    normative_source_ids: tuple[str, ...]
    source_path: Path
    source_span: str
    title: str
    rule: str
    rationale: str
    judgeability: Judgeability

    @pydantic.field_validator("normative_source_ids", mode="before")
    @classmethod
    def validate_normative_source_ids(cls, value: Any) -> Any:
        """Allow serialized list values."""
        if isinstance(value, list):
            return tuple(value)
        return value

    @pydantic.field_validator("source_path", mode="before")
    @classmethod
    def validate_source_path(cls, value: Any) -> Any:
        """Allow serialized path strings."""
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("judgeability", mode="before")
    @classmethod
    def validate_judgeability(cls, value: Any) -> Any:
        """Allow serialized judgeability strings."""
        if isinstance(value, str):
            return Judgeability(value)
        return value


_ATOMIC_ADAPTER = pydantic.TypeAdapter(tuple[AtomicConstraint, ...])


def load_atomic_constraints(constraints_file: Path) -> tuple[AtomicConstraint, ...]:
    """Load atomic constraints from a JSON file."""
    try:
        loaded = json.loads(constraints_file.read_text(encoding="utf-8"))
        raw_constraints = loaded["constraints"]
        return _ATOMIC_ADAPTER.validate_python(raw_constraints)
    except (KeyError, TypeError, json.JSONDecodeError, pydantic.ValidationError) as validation_error:
        raise error.ConstraintCatalogError(
            f"Invalid atomic constraint definition in {constraints_file}",
        ) from validation_error


def render_atomic_summary(constraints: tuple[AtomicConstraint, ...]) -> str:
    """Render a markdown summary for atomic constraints."""
    lines = [
        "# Atomic Constraints",
        "",
        "| ID | Judgeability | Rule |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {constraint.id} | {constraint.judgeability.value} | {constraint.rule} |" for constraint in constraints
    )
    return "\n".join(lines).strip() + "\n"
