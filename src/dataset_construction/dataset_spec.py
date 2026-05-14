"""Dataset construction specification (serializable to/from JSON)."""

import json
from pathlib import Path

import base
import error
import pydantic
import verification


class DatasetSpec(base.FrozenModel):
    """Parameters needed to build the benchmark dataset from merged PRs."""

    github_repo: str
    repo_path: Path
    target_paths: tuple[str, ...]
    since: str | None = None
    pr_search_labels: tuple[str, ...]
    datasets_root: Path
    pr_search_limit: int = 1000
    pr_search_until: str | None = None
    pr_search_window_days: int = 30
    pr_limit: int | None = None
    exclusion_patterns: tuple[str, ...] = ()
    min_changed_files: int = 1
    max_changed_files: int | None = None
    min_changed_lines: int = 0
    max_changed_lines: int | None = None
    require_production_go_change: bool = False
    model_cutoffs: dict[str, str] = pydantic.Field(default_factory=dict)
    required_pr_labels: tuple[str, ...] = ()
    excluded_pr_labels: tuple[str, ...] = ()
    pr_cache_dir: Path | None = None
    verification_level: verification.VerificationLevel = verification.VerificationLevel.NONE
    rejected_root: Path | None = None

    @pydantic.field_validator("verification_level", mode="before")
    @classmethod
    def validate_verification_level(cls, value: object) -> object:
        if isinstance(value, str):
            return verification.VerificationLevel(value)
        return value

    @pydantic.field_validator(
        "repo_path",
        "datasets_root",
        "rejected_root",
        "pr_cache_dir",
        mode="before",
    )
    @classmethod
    def validate_path_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator(
        "target_paths",
        "exclusion_patterns",
        "pr_search_labels",
        "required_pr_labels",
        "excluded_pr_labels",
        mode="before",
    )
    @classmethod
    def validate_string_tuples(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


_SPEC_ADAPTER = pydantic.TypeAdapter(DatasetSpec)


def load_dataset_spec(spec_path: Path) -> DatasetSpec:
    """Load a DatasetSpec from a JSON file."""
    try:
        document = json.loads(spec_path.read_text(encoding="utf-8"))
        return _SPEC_ADAPTER.validate_python(document)
    except (OSError, json.JSONDecodeError, pydantic.ValidationError) as validation_error:
        raise error.ConstraintCatalogError(
            f"Invalid dataset spec in {spec_path}",
        ) from validation_error
