"""Deterministic kube-api-linter relation hints for draft constraints."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import base
import sentence_constraint_candidate


class KubeApiLinterRelationTask(base.FrozenModel):
    """One draft constraint that may relate to kube-api-linter rules."""

    id: str
    original: str
    constraint: str


class KubeApiLinterRelation(base.FrozenModel):
    """Reviewer-facing kube-api-linter rule hints for one draft constraint."""

    task_id: str
    rules: tuple[str, ...]


class KubeApiLinterRelationReport(base.FrozenModel):
    """Deterministic kube-api-linter relation report."""

    relations: tuple[KubeApiLinterRelation, ...]


class ExistingKubeApiLinterRelationReportValidation(base.FrozenModel):
    """Whether an existing kube-api-linter relation report can be reused."""

    is_reusable: bool
    reason: str


def build_relation_tasks(
    draft_report: sentence_constraint_candidate.SentenceConstraintCandidateReport,
) -> tuple[KubeApiLinterRelationTask, ...]:
    """Build relation tasks from draft constraints."""
    return tuple(
        KubeApiLinterRelationTask(
            id=candidate.task_id,
            original=candidate.original,
            constraint=candidate.constraint,
        )
        for candidate in draft_report.candidates
    )


def select_related_rules(tasks: tuple[KubeApiLinterRelationTask, ...]) -> KubeApiLinterRelationReport:
    """Select high-confidence kube-api-linter rule hints for draft constraints."""
    return KubeApiLinterRelationReport(
        relations=tuple(KubeApiLinterRelation(task_id=task.id, rules=_related_rules(task)) for task in tasks),
    )


def load_relation_report(path: Path) -> KubeApiLinterRelationReport:
    """Load a kube-api-linter relation report."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("Kube-api-linter relation report must contain a JSON object.")
    report_document = cast(dict[str, object], document)
    return KubeApiLinterRelationReport(
        relations=tuple(_relation_from_json(relation) for relation in _list_field(report_document, "relations")),
    )


def save_relation_report(report: KubeApiLinterRelationReport, output_path: Path) -> None:
    """Save kube-api-linter relation report as JSON."""
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_existing_report(
    report: KubeApiLinterRelationReport,
    tasks: tuple[KubeApiLinterRelationTask, ...],
) -> ExistingKubeApiLinterRelationReportValidation:
    """Check whether an existing relation report fully covers the current task set."""
    expected_task_ids = {task.id for task in tasks}
    relation_task_ids = {relation.task_id for relation in report.relations}
    missing_task_ids = expected_task_ids - relation_task_ids
    if missing_task_ids:
        return ExistingKubeApiLinterRelationReportValidation(is_reusable=False, reason="missing_task_relations")
    extra_task_ids = relation_task_ids - expected_task_ids
    if extra_task_ids:
        return ExistingKubeApiLinterRelationReportValidation(is_reusable=False, reason="unknown_task_relations")
    return ExistingKubeApiLinterRelationReportValidation(is_reusable=True, reason="complete")


def _related_rules(task: KubeApiLinterRelationTask) -> tuple[str, ...]:
    text = _normalized_text(task)
    rules: list[str] = []
    if _matches_integer_rule(text):
        rules.append("integers")
    if _matches_optional_or_required_rule(text):
        rules.append("optionalorrequired")
    if _matches_optional_fields_rule(text):
        rules.append("optionalfields")
    if _matches_no_timestamp_rule(text):
        rules.append("notimestamp")
    if _matches_conditions_rule(text):
        rules.append("conditions")
    if _matches_ssa_tags_rule(text):
        rules.append("ssatags")
    if _matches_max_length_rule(text):
        rules.append("maxlength (disabled)")
    if _matches_no_floats_rule(text):
        rules.append("nofloats (disabled)")
    if _matches_no_phase_rule(text):
        rules.append("nophase (disabled)")
    return tuple(rules)


def _normalized_text(task: KubeApiLinterRelationTask) -> str:
    return f"{task.original}\n{task.constraint}".casefold()


def _matches_integer_rule(text: str) -> bool:
    return bool(re.search(r"\bint32\b|\bint64\b", text)) and bool(
        re.search(r"\binteger fields?\b|\bgo int\b|\bnot [`']?int[`']?\b|\binstead of [`']?int[`']?\b", text),
    )


def _matches_optional_or_required_rule(text: str) -> bool:
    return "+optional" in text or "+required" in text or "optional or required" in text


def _matches_optional_fields_rule(text: str) -> bool:
    return "optional" in text and bool(re.search(r"\bpointer\b|\bomitempty\b|\bomitzero\b", text))


def _matches_no_timestamp_rule(text: str) -> bool:
    return bool(
        re.search(
            r"\bmust not use [`']?stamp[`']?\b|\bdo not use [`']?stamp[`']?\b|\bshould not use [`']?stamp[`']?\b", text
        ),
    ) or bool(re.search(r"\bcalled \w*time\b", text) and re.search(r"\btimestamp\b|\bstamp\b", text))


def _matches_conditions_rule(text: str) -> bool:
    return "metav1.condition" in text


def _matches_ssa_tags_rule(text: str) -> bool:
    return "+listtype" in text or "listtype" in text or "+maptype" in text or "maptype" in text


def _matches_max_length_rule(text: str) -> bool:
    return bool(re.search(r"\bmaximum length\b|\bmax length\b|\bmaxlength\b|\bmaxitems\b", text))


def _matches_no_floats_rule(text: str) -> bool:
    return bool(re.search(r"\bfloat\b|\bfloating-point\b", text)) and bool(
        re.search(r"\bavoid\b|\bmust not\b|\bnever\b|\bshould not\b", text),
    )


def _matches_no_phase_rule(text: str) -> bool:
    return "phase" in text and bool(re.search(r"\bdeprecated\b|\bconditions?\b", text))


def _relation_from_json(value: object) -> KubeApiLinterRelation:
    if not isinstance(value, dict):
        raise TypeError("Kube-api-linter relation must be a JSON object.")
    relation = cast(dict[str, object], value)
    task_id = relation.get("task_id")
    if not isinstance(task_id, str):
        raise TypeError("Kube-api-linter relation task_id must be a string.")
    return KubeApiLinterRelation(task_id=task_id, rules=tuple(_str_list_field(relation, "rules")))


def _list_field(document: dict[str, object], field_name: str) -> list[object]:
    value = document.get(field_name)
    if not isinstance(value, list):
        raise TypeError(f"`{field_name}` must be a JSON array.")
    return cast(list[object], value)


def _str_list_field(document: dict[str, Any], field_name: str) -> list[str]:
    value = document.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"`{field_name}` must be a JSON string array.")
    return value
