import json
from pathlib import Path

import kube_api_linter_relation
import sentence_constraint_candidate


def test_build_relation_tasks_uses_draft_constraints() -> None:
    candidate = _candidate(
        task_id="block_0001_s1",
        original="Integer fields should use int32 or int64.",
        constraint="API integer fields must use int32 or int64 instead of int.",
    )

    tasks = kube_api_linter_relation.build_relation_tasks(
        sentence_constraint_candidate.SentenceConstraintCandidateReport(candidates=(candidate,)),
    )

    assert tasks == (
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="block_0001_s1",
            original="Integer fields should use int32 or int64.",
            constraint="API integer fields must use int32 or int64 instead of int.",
        ),
    )


def test_select_related_rules_matches_only_high_confidence_linter_patterns() -> None:
    tasks = (
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="integer",
            original="Integer fields should use int32 or int64.",
            constraint="API integer fields must use int32 or int64 instead of int.",
        ),
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="optionality",
            original="Fields must be either optional or required.",
            constraint="Fields must explicitly use +optional or +required markers.",
        ),
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="semantic_condition",
            original="Conditions should convey properties users care about.",
            constraint="Conditions should describe properties that matter to users.",
        ),
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="disabled_max_length",
            original="Strings should have maximum lengths.",
            constraint="String fields should define a maximum length.",
        ),
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="metadata_timestamp_reference",
            original="Object metadata includes creationTimestamp and deletionTimestamp as RFC 3339 date-time strings.",
            constraint="Objects should include metadata with creationTimestamp and deletionTimestamp date-time fields.",
        ),
    )

    report = kube_api_linter_relation.select_related_rules(tasks)

    assert tuple((relation.task_id, relation.rules) for relation in report.relations) == (
        ("integer", ("integers",)),
        ("optionality", ("optionalorrequired",)),
        ("semantic_condition", ()),
        ("disabled_max_length", ("maxlength (disabled)",)),
        ("metadata_timestamp_reference", ()),
    )


def test_load_save_and_validate_relation_report(tmp_path: Path) -> None:
    output_path = tmp_path / "sentence_kube_api_linter_relations.json"
    tasks = (
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="block_0001_s1",
            original="Fields must be either optional or required.",
            constraint="Fields must use +optional or +required markers.",
        ),
    )
    report = kube_api_linter_relation.KubeApiLinterRelationReport(
        relations=(
            kube_api_linter_relation.KubeApiLinterRelation(
                task_id="block_0001_s1",
                rules=("optionalorrequired",),
            ),
        ),
    )

    kube_api_linter_relation.save_relation_report(report, output_path)
    loaded = kube_api_linter_relation.load_relation_report(output_path)
    validation = kube_api_linter_relation.validate_existing_report(loaded, tasks)

    assert loaded == report
    assert validation.is_reusable is True
    assert json.loads(output_path.read_text(encoding="utf-8"))["relations"][0]["rules"] == ["optionalorrequired"]


def test_validate_existing_report_rejects_missing_or_unknown_task_relations() -> None:
    tasks = (
        kube_api_linter_relation.KubeApiLinterRelationTask(
            id="block_0001_s1",
            original="Fields must be either optional or required.",
            constraint="Fields must use +optional or +required markers.",
        ),
    )

    missing = kube_api_linter_relation.validate_existing_report(
        kube_api_linter_relation.KubeApiLinterRelationReport(relations=()),
        tasks,
    )
    unknown = kube_api_linter_relation.validate_existing_report(
        kube_api_linter_relation.KubeApiLinterRelationReport(
            relations=(
                kube_api_linter_relation.KubeApiLinterRelation(task_id="block_0001_s1", rules=()),
                kube_api_linter_relation.KubeApiLinterRelation(task_id="unknown", rules=()),
            ),
        ),
        tasks,
    )

    assert missing.reason == "missing_task_relations"
    assert unknown.reason == "unknown_task_relations"


def _candidate(
    *, task_id: str, original: str, constraint: str
) -> sentence_constraint_candidate.SentenceConstraintCandidate:
    return sentence_constraint_candidate.SentenceConstraintCandidate(
        id=task_id,
        task_id=task_id,
        source_span="10-10",
        source_strength=("obligation",),
        original=original,
        constraint=constraint,
    )
