"""Normative constraints extracted directly from guideline text."""

import enum
import json
from pathlib import Path
from typing import Any

import base
import error
import pydantic


class NormativeSignal(enum.StrEnum):
    """Strength signal family derived from the source wording."""

    MUST_UPPER = "MUST"
    SHOULD_UPPER = "SHOULD"
    MAY_UPPER = "MAY"
    MUST = "must"
    SHOULD = "should"
    MAY = "may"
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    PREFERRED = "preferred"
    DEPRECATED = "deprecated"


class NormativeConstraint(base.FrozenModel):
    """Normative statement extracted from a source document."""

    id: str
    source_path: Path
    source_span: str
    text: str
    strength_signal: NormativeSignal
    atomicizable: bool
    notes: str = ""

    @pydantic.field_validator("source_path", mode="before")
    @classmethod
    def validate_source_path(cls, value: Any) -> Any:
        """Allow serialized path strings."""
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("strength_signal", mode="before")
    @classmethod
    def validate_strength_signal(cls, value: Any) -> Any:
        """Allow serialized strength signal strings."""
        if isinstance(value, str):
            return NormativeSignal(value)
        return value


_NORMATIVE_ADAPTER = pydantic.TypeAdapter(tuple[NormativeConstraint, ...])


def load_normative_constraints(constraints_file: Path) -> tuple[NormativeConstraint, ...]:
    """Load normative constraints from a JSON file."""
    try:
        loaded = json.loads(constraints_file.read_text(encoding="utf-8"))
        raw_constraints = loaded["constraints"]
        return _NORMATIVE_ADAPTER.validate_python(raw_constraints)
    except (KeyError, TypeError, json.JSONDecodeError, pydantic.ValidationError) as validation_error:
        raise error.ConstraintCatalogError(
            f"Invalid normative constraint definition in {constraints_file}",
        ) from validation_error
