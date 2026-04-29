"""Configuration models for guideline source selection."""

from __future__ import annotations

import json
from pathlib import Path

import base
import error
import pydantic
import source_selection


class SourceSelectionConfig(base.FrozenModel):
    """Configuration for selecting guideline sources from commit history."""

    repo_path: Path | None = None
    target_paths: tuple[str, ...]
    since: str
    grep: str
    minimum_match_count: int
    markdown_report_path: Path
    json_report_path: Path
    sources: tuple[source_selection.GuidelineSource, ...]

    @pydantic.field_validator("repo_path", "markdown_report_path", "json_report_path", mode="before")
    @classmethod
    def validate_path_fields(cls, value: object) -> object:
        """Allow serialized path strings."""
        if value is None:
            return value
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("target_paths", "sources", mode="before")
    @classmethod
    def validate_tuple_fields(cls, value: object) -> object:
        """Allow serialized list values for tuple fields."""
        if isinstance(value, list):
            return tuple(value)
        return value


_CONFIG_ADAPTER = pydantic.TypeAdapter(SourceSelectionConfig)


def load_source_selection_config(config_path: Path) -> SourceSelectionConfig:
    """Load source selection configuration from JSON."""
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
        return _CONFIG_ADAPTER.validate_python(document)
    except (OSError, json.JSONDecodeError, pydantic.ValidationError) as validation_error:
        raise error.ConstraintCatalogError(
            f"Invalid source selection config in {config_path}",
        ) from validation_error
