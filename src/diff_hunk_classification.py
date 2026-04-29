"""Classify unified diff hunks by API-conventions relevance."""

from __future__ import annotations

import enum
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import base
import pydantic


class HunkClassification(enum.StrEnum):
    """Coarse hunk classes for API Conventions candidate filtering."""

    API_TYPE = "api_type"
    API_VALIDATION = "api_validation"
    API_DEFAULTING = "api_defaulting"
    API_CONVERSION_VERSIONING = "api_conversion_versioning"
    API_REST_BEHAVIOR = "api_rest_behavior"
    API_DISCOVERY_OPENAPI = "api_discovery_openapi"
    NON_API_DEPENDENCY = "non_api_dependency"
    NON_API_LOGGING = "non_api_logging"
    NON_API_CONTEXT_PLUMBING = "non_api_context_plumbing"
    NON_API_METRIC = "non_api_metric"
    NON_API_LINT = "non_api_lint"
    NON_API_TEST_ONLY = "non_api_test_only"
    NON_API_OWNERSHIP = "non_api_ownership"
    NON_API_OTHER = "non_api_other"


API_CANDIDATE_CLASSIFICATIONS = frozenset(
    {
        HunkClassification.API_TYPE,
        HunkClassification.API_VALIDATION,
        HunkClassification.API_DEFAULTING,
        HunkClassification.API_CONVERSION_VERSIONING,
        HunkClassification.API_REST_BEHAVIOR,
        HunkClassification.API_DISCOVERY_OPENAPI,
    },
)


class DiffHunk(base.FrozenModel):
    """A parsed unified diff hunk with a coarse relevance classification."""

    file_path: Path
    header: str
    lines: tuple[str, ...]
    classification: HunkClassification
    reason: str

    @pydantic.field_validator("file_path", mode="before")
    @classmethod
    def validate_file_path(cls, value: Any) -> Any:
        """Allow serialized path strings."""
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("lines", mode="before")
    @classmethod
    def validate_lines(cls, value: Any) -> Any:
        """Allow serialized line lists."""
        if isinstance(value, list):
            return tuple(cast("list[str]", value))
        return value

    @property
    def is_api_conventions_candidate(self) -> bool:
        """Return whether this hunk should be judged against API Conventions."""
        return self.classification in API_CANDIDATE_CLASSIFICATIONS


class PatchClassification(base.FrozenModel):
    """Classification result for all hunks in one patch."""

    hunks: tuple[DiffHunk, ...]

    @pydantic.field_validator("hunks", mode="before")
    @classmethod
    def validate_hunks(cls, value: Any) -> Any:
        """Allow serialized hunk lists."""
        if isinstance(value, list):
            return tuple(cast("list[DiffHunk | dict[str, Any]]", value))
        return value

    @property
    def candidate_hunks(self) -> tuple[DiffHunk, ...]:
        """Return hunks retained for API Conventions matching."""
        return tuple(hunk for hunk in self.hunks if hunk.is_api_conventions_candidate)

    @property
    def excluded_hunks(self) -> tuple[DiffHunk, ...]:
        """Return hunks excluded from API Conventions matching."""
        return tuple(hunk for hunk in self.hunks if not hunk.is_api_conventions_candidate)

    @property
    def has_api_conventions_candidates(self) -> bool:
        """Return whether any hunk remains after API surface gating."""
        return len(self.candidate_hunks) > 0


_DIFF_HEADER_PATTERN = re.compile(r"^diff --git a/(?P<old_path>.+) b/(?P<new_path>.+)$")
_HUNK_HEADER_PATTERN = re.compile(r"^@@ .+ @@")
_CLASSIFIERS: tuple[tuple[Callable[[str, str, str], bool], HunkClassification, str], ...] = (
    (
        lambda path, _changed, _lower: _is_dependency_file(path),
        HunkClassification.NON_API_DEPENDENCY,
        "dependency file",
    ),
    (
        lambda path, _changed, _lower: _is_ownership_file(path),
        HunkClassification.NON_API_OWNERSHIP,
        "ownership metadata",
    ),
    (
        lambda path, _changed, lower: _is_metric_hunk(path, lower),
        HunkClassification.NON_API_METRIC,
        "metrics-only surface",
    ),
    (
        lambda _path, _changed, lower: _is_logging_hunk(lower),
        HunkClassification.NON_API_LOGGING,
        "logging-only surface",
    ),
    (
        lambda _path, _changed, lower: _is_context_plumbing_hunk(lower),
        HunkClassification.NON_API_CONTEXT_PLUMBING,
        "context plumbing without API behavior change",
    ),
    (
        lambda path, _changed, lower: _is_lint_hunk(path, lower),
        HunkClassification.NON_API_LINT,
        "lint or language modernization",
    ),
    (
        lambda path, _changed, _lower: _is_test_file(path),
        HunkClassification.NON_API_TEST_ONLY,
        "test-only hunk",
    ),
    (
        lambda path, changed, _lower: _is_api_validation_hunk(path, changed),
        HunkClassification.API_VALIDATION,
        "API validation code",
    ),
    (
        lambda path, changed, _lower: _is_api_defaulting_hunk(path, changed),
        HunkClassification.API_DEFAULTING,
        "API defaulting code",
    ),
    (
        lambda path, changed, _lower: _is_api_conversion_versioning_hunk(path, changed),
        HunkClassification.API_CONVERSION_VERSIONING,
        "API conversion or version registration",
    ),
    (
        lambda path, changed, _lower: _is_api_discovery_openapi_hunk(path, changed),
        HunkClassification.API_DISCOVERY_OPENAPI,
        "API discovery or OpenAPI code",
    ),
    (
        lambda path, changed, _lower: _is_api_rest_behavior_hunk(path, changed),
        HunkClassification.API_REST_BEHAVIOR,
        "API REST operation behavior",
    ),
    (
        lambda path, changed, _lower: _is_api_type_hunk(path, changed),
        HunkClassification.API_TYPE,
        "API type definition",
    ),
)


def classify_patch(patch_text: str) -> PatchClassification:
    """Classify all hunks in a unified diff patch."""
    hunks: list[DiffHunk] = []
    current_file: Path | None = None
    current_header: str | None = None
    current_lines: list[str] = []

    for line in patch_text.splitlines():
        diff_match = _DIFF_HEADER_PATTERN.match(line)
        if diff_match is not None:
            _append_hunk(hunks, current_file, current_header, current_lines)
            current_file = Path(diff_match.group("new_path"))
            current_header = None
            current_lines = []
            continue

        if _HUNK_HEADER_PATTERN.match(line) is not None:
            _append_hunk(hunks, current_file, current_header, current_lines)
            current_header = line
            current_lines = []
            continue

        if current_header is not None:
            current_lines.append(line)

    _append_hunk(hunks, current_file, current_header, current_lines)
    return PatchClassification(hunks=tuple(hunks))


def _append_hunk(
    hunks: list[DiffHunk],
    file_path: Path | None,
    header: str | None,
    lines: list[str],
) -> None:
    if file_path is None or header is None:
        return
    classification, reason = classify_hunk(file_path, tuple(lines))
    hunks.append(
        DiffHunk(
            file_path=file_path,
            header=header,
            lines=tuple(lines),
            classification=classification,
            reason=reason,
        ),
    )


def classify_hunk(file_path: Path, lines: tuple[str, ...]) -> tuple[HunkClassification, str]:
    """Classify one diff hunk using path and changed-line signals."""
    path = file_path.as_posix()
    changed_text = "\n".join(_changed_lines(lines))
    path_lower = path.lower()
    changed_lower = changed_text.lower()

    for predicate, classification, reason in _CLASSIFIERS:
        if predicate(path_lower, changed_text, changed_lower):
            return classification, reason
    return HunkClassification.NON_API_OTHER, "no API surface signal"


def _changed_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(line[1:] for line in lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


def _is_dependency_file(path: str) -> bool:
    name = Path(path).name
    return name in {"go.mod", "go.sum", "vendor.json", "vendor/modules.txt"}


def _is_ownership_file(path: str) -> bool:
    return Path(path).name in {"OWNERS", "OWNERS_ALIASES"}


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.endswith("_test.go") or "/test/" in path or "/testing/" in path


def _is_metric_hunk(path_lower: str, changed_lower: str) -> bool:
    metric_signals = (
        "/metrics/",
        "metrics.go",
        "counteropts",
        "gaugeopts",
        "histogramopts",
        "withlabelvalues",
        "stabilitylevel",
    )
    return any(signal in path_lower or signal in changed_lower for signal in metric_signals)


def _is_logging_hunk(changed_lower: str) -> bool:
    logging_signals = (
        "klog.",
        "logger.",
        "handleerrorwithcontext",
        "handleerrorwithlogger",
        "handlecrashwithlogger",
        "logcheck",
        "contextual logging",
    )
    return any(signal in changed_lower for signal in logging_signals)


def _is_context_plumbing_hunk(changed_lower: str) -> bool:
    context_plumbing_signals = (
        "context.todo()",
        "context.background()",
        "req.context()",
        "ws.request().context()",
        "newwatchencoder(ctx",
        "shouldrecordwatchlistlatency(ctx",
        "shouldrecordwatchlistlatency(req.context()",
    )
    return any(signal in changed_lower for signal in context_plumbing_signals)


def _is_lint_hunk(path_lower: str, changed_lower: str) -> bool:
    lint_signals = (
        "golangci",
        "gocritic",
        "modernize",
        "slices.sort",
        "sort.slice",
        " =  // capture loop variable",
    )
    return ".golangci" in path_lower or any(signal in changed_lower for signal in lint_signals)


def _is_api_validation_hunk(path_lower: str, changed_text: str) -> bool:
    validation_path = "/validation/" in path_lower or path_lower.endswith("/validation.go")
    validation_signals = (
        "Validate",
        "validate",
        "field.Required",
        "field.Invalid",
        "field.TooLong",
        "ValidateObjectMeta",
        "ValidateObjectMetaUpdate",
    )
    return validation_path and any(signal in changed_text for signal in validation_signals)


def _is_api_defaulting_hunk(path_lower: str, changed_text: str) -> bool:
    defaulting_path = path_lower.endswith(("/defaults.go", "/zz_generated.defaults.go"))
    defaulting_signals = ("SetDefaults_", "+default", "Default")
    return defaulting_path and any(signal in changed_text for signal in defaulting_signals)


def _is_api_conversion_versioning_hunk(path_lower: str, changed_text: str) -> bool:
    conversion_path = (
        path_lower.endswith(("/conversion.go", "/register.go", "/install.go"))
        or "zz_generated.conversion.go" in path_lower
    )
    versioning_signals = (
        "SchemeGroupVersion",
        "AddToScheme",
        "SetVersionPriority",
        "GroupVersionKind",
        "GroupVersionResource",
        "ObjectKinds",
        "TypeMeta",
    )
    return conversion_path and any(signal in changed_text for signal in versioning_signals)


def _is_api_discovery_openapi_hunk(path_lower: str, changed_text: str) -> bool:
    discovery_path = "/discovery/" in path_lower or "/openapi/" in path_lower
    discovery_signals = ("GroupVersion", "GroupVersionResource", "Accept", "apiVersion", "kind")
    return discovery_path and any(signal in changed_text for signal in discovery_signals)


def _is_api_rest_behavior_hunk(path_lower: str, changed_text: str) -> bool:
    rest_path = (
        "/registry/" in path_lower
        or "/endpoints/handlers/" in path_lower
        or path_lower.endswith("/strategy.go")
        or "/rest/" in path_lower
    )
    rest_signals = (
        "ListOptions",
        "ResourceVersion",
        "Watch",
        "Create",
        "Update",
        "Delete",
        "Get",
        "/status",
        "RequestInfo",
    )
    return rest_path and any(signal in changed_text for signal in rest_signals)


def _is_api_type_hunk(path_lower: str, changed_text: str) -> bool:
    api_type_path = path_lower.endswith("/types.go") and (
        "/pkg/apis/" in path_lower or "/staging/src/k8s.io/api/" in path_lower
    )
    type_signals = ("json:", "+optional", "+required", "metav1.TypeMeta", "ObjectMeta", "Spec", "Status")
    return api_type_path and any(signal in changed_text for signal in type_signals)
