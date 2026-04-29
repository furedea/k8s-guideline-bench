import json
from pathlib import Path

import source_selection


def test_select_guideline_sources_marks_source_selected_when_matches_clear_threshold() -> None:
    source = source_selection.GuidelineSource(
        id="feature_gate",
        title="Feature gate template",
        path=Path("/tmp/kube_features.go"),
        summary="Feature gate declarations",
        keyword_patterns=(r"feature gate", r"\bbeta\b"),
        rationale="Covers feature lifecycle refactors.",
    )
    commits = (
        source_selection.RefactorCommit(
            sha="a" * 40,
            date="2026-02-20",
            subject="DRA device taints: graduate to beta",
        ),
        source_selection.RefactorCommit(
            sha="b" * 40,
            date="2026-02-12",
            subject="Remove references to UserNamespacesSupport feature gate from core types",
        ),
        source_selection.RefactorCommit(
            sha="c" * 40,
            date="2026-02-11",
            subject="remove the InPlacePodVerticalScalingAllocatedStatus feature gate",
        ),
    )

    coverage = source_selection.select_guideline_sources((source,), commits, minimum_match_count=2)

    assert coverage == (
        source_selection.SourceCoverage(
            source=source,
            matched_commit_count=3,
            matched_examples=commits,
            selected=True,
        ),
    )


def test_select_guideline_sources_sorts_by_match_count_descending() -> None:
    validation_source = source_selection.GuidelineSource(
        id="validation",
        title="Validation rules",
        path=Path("/tmp/linter.yaml"),
        summary="Validation marker rules",
        keyword_patterns=(r"validation",),
        rationale="Validation",
    )
    feature_source = source_selection.GuidelineSource(
        id="feature_gate",
        title="Feature gates",
        path=Path("/tmp/kube_features.go"),
        summary="Feature gate rules",
        keyword_patterns=(r"feature gate",),
        rationale="Feature gate lifecycle",
    )
    commits = (
        source_selection.RefactorCommit(
            sha="a" * 40,
            date="2026-02-12",
            subject="address feedback: refactor declarative validation migration checks",
        ),
        source_selection.RefactorCommit(
            sha="b" * 40,
            date="2026-02-11",
            subject="remove the InPlacePodVerticalScalingAllocatedStatus feature gate",
        ),
        source_selection.RefactorCommit(
            sha="c" * 40,
            date="2026-01-07",
            subject="Migrate ResourceSlice map key validation to declarative validation",
        ),
    )

    coverage = source_selection.select_guideline_sources(
        (feature_source, validation_source),
        commits,
        minimum_match_count=1,
    )

    assert [item.source.id for item in coverage] == ["validation", "feature_gate"]
    assert [item.matched_commit_count for item in coverage] == [2, 1]


def test_render_selection_markdown_includes_examples() -> None:
    source = source_selection.GuidelineSource(
        id="api_rules",
        title="API rules",
        path=Path("/tmp/api-rules/README.md"),
        summary="API rules",
        keyword_patterns=(r"\bapi\b",),
        rationale="API conventions",
    )
    commit = source_selection.RefactorCommit(
        sha="d" * 40,
        date="2026-03-19",
        subject="api: enable optionalorrequired linter for authentication API",
    )
    coverage = (
        source_selection.SourceCoverage(
            source=source,
            matched_commit_count=1,
            matched_examples=(commit,),
            selected=True,
        ),
    )

    report = source_selection.render_selection_markdown(coverage, Path("/tmp"))

    assert "# Guideline Source Selection" in report
    assert "API rules" in report
    assert "2026-03-19" in report
    assert "optionalorrequired linter" in report
    assert "`api-rules/README.md`" in report


def test_save_selection_report_uses_repo_relative_paths(tmp_path: Path) -> None:
    source = source_selection.GuidelineSource(
        id="api_rules",
        title="API rules",
        path=Path("/tmp/kubernetes/api/api-rules/README.md"),
        summary="API rules",
        keyword_patterns=(r"\bapi\b",),
        rationale="API conventions",
    )
    coverage = (
        source_selection.SourceCoverage(
            source=source,
            matched_commit_count=0,
            matched_examples=(),
            selected=False,
        ),
    )
    output_path = tmp_path / "report.json"

    source_selection.save_selection_report(output_path, coverage, Path("/tmp/kubernetes"))

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["sources"][0]["path"] == "api/api-rules/README.md"
