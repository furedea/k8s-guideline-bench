"""Tests for fair-report CLI helpers."""

import json
from pathlib import Path

import compute_fair_report
import fair_summary
import judge


def _write_judgments(
    results_root: Path,
    run_id: str,
    instance_id: str,
    judgments: tuple[judge.ConstraintJudgment, ...],
) -> None:
    instance_dir = results_root / run_id / instance_id
    instance_dir.mkdir(parents=True)
    instance_judgment = judge.InstanceJudgment(
        instance_id=instance_id,
        run_id=run_id,
        judgments=judgments,
    )
    _ = (instance_dir / "judgments.json").write_text(
        json.dumps(instance_judgment.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _write_gold_scope(results_root: Path, instance_id: str, in_scope_ids: tuple[str, ...]) -> None:
    judgments = tuple(
        judge.ConstraintJudgment(
            constraint_id=cid,
            verdict=judge.JudgeVerdict.COMPLIANT,
            confidence=0.9,
            rationale="",
            patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
        )
        for cid in in_scope_ids
    )
    _write_judgments(results_root, "gold_scope", instance_id, judgments)


def _compliant_applied(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="",
        patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
    )


def _violated(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        verdict=judge.JudgeVerdict.VIOLATED,
        confidence=0.8,
        rationale="",
    )


def test_load_run_judgments_returns_persisted_instance_judgments(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    _write_judgments(
        results_root,
        run_id="pilot_no_constraints",
        instance_id="42",
        judgments=(_compliant_applied("c1"),),
    )
    _write_judgments(
        results_root,
        run_id="pilot_no_constraints",
        instance_id="43",
        judgments=(_violated("c1"),),
    )

    loaded = compute_fair_report._load_run_judgments(results_root, run_id="pilot_no_constraints")

    instance_ids = tuple(j.instance_id for j in loaded)
    assert sorted(instance_ids) == ["42", "43"]


def test_load_run_judgments_prefers_gold_scope_judge_results_when_present(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    _write_judgments(
        results_root,
        run_id="pilot_no_constraints",
        instance_id="42",
        judgments=(_compliant_applied("full"),),
    )
    _write_judgments(
        results_root,
        run_id="pilot_no_constraints__gold_scope",
        instance_id="42",
        judgments=(_compliant_applied("scoped"),),
    )

    loaded = compute_fair_report._load_run_judgments(results_root, run_id="pilot_no_constraints")

    assert loaded[0].run_id == "pilot_no_constraints"
    assert tuple(j.constraint_id for j in loaded[0].judgments) == ("scoped",)


def test_load_run_judgments_skips_directories_without_judgments_file(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    (results_root / "pilot_no_constraints" / "42").mkdir(parents=True)

    loaded = compute_fair_report._load_run_judgments(results_root, run_id="pilot_no_constraints")

    assert loaded == ()


def test_compute_fair_report_emits_summary_per_run_using_gold_scope(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    _write_gold_scope(results_root, "42", in_scope_ids=("c1", "c2"))
    _write_judgments(
        results_root,
        run_id="pilot_no_constraints",
        instance_id="42",
        judgments=(_compliant_applied("c1"), _violated("c2")),
    )
    _write_judgments(
        results_root,
        run_id="pilot_atomic",
        instance_id="42",
        judgments=(_compliant_applied("c1"), _compliant_applied("c2")),
    )

    report = compute_fair_report.compute_fair_report(
        results_root=results_root,
        run_ids=("pilot_no_constraints", "pilot_atomic"),
    )

    assert report.results_root == results_root
    summaries = {summary.run_id: summary for summary in report.runs}
    no_constraints = summaries["pilot_no_constraints"]
    assert no_constraints.common_scope_total == 2
    assert no_constraints.newly_satisfied == 1
    atomic = summaries["pilot_atomic"]
    assert atomic.common_scope_total == 2
    assert atomic.newly_satisfied == 2


def test_compute_fair_report_persists_fair_report_json(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    _write_gold_scope(results_root, "42", in_scope_ids=("c1",))
    _write_judgments(
        results_root,
        run_id="pilot",
        instance_id="42",
        judgments=(_compliant_applied("c1"),),
    )

    _ = compute_fair_report.compute_fair_report(
        results_root=results_root,
        run_ids=("pilot",),
    )

    document = json.loads((results_root / "fair_report.json").read_text(encoding="utf-8"))
    assert document["runs"][0]["run_id"] == "pilot"
    assert document["runs"][0]["newly_satisfied"] == 1
    assert document["runs"][0]["common_scope_total"] == 1


def test_compute_fair_report_returns_zero_when_no_scope_for_instance(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    _write_judgments(
        results_root,
        run_id="pilot",
        instance_id="42",
        judgments=(_compliant_applied("c1"),),
    )

    report = compute_fair_report.compute_fair_report(
        results_root=results_root,
        run_ids=("pilot",),
    )

    summary = report.runs[0]
    assert summary.common_scope_total == 0
    assert summary.newly_satisfied == 0
    assert summary.out_of_scope_newly_satisfied == 1


def test_fair_report_round_trips_via_pydantic(tmp_path: Path) -> None:
    summary = fair_summary.FairJudgmentSummary(
        run_id="pilot",
        common_scope_total=3,
        newly_satisfied=2,
        newly_satisfied_rate=2 / 3,
        out_of_scope_newly_satisfied=0,
        instances_judged=1,
    )
    report = compute_fair_report.FairReport(
        results_root=tmp_path,
        runs=(summary,),
    )

    document = json.loads(report.model_dump_json())

    assert document["runs"][0]["run_id"] == "pilot"
    assert document["results_root"] == str(tmp_path)


def test_render_report_outputs_per_problem_hits_without_decimal_scores(tmp_path: Path) -> None:
    summary = fair_summary.FairJudgmentSummary(
        run_id="pilot_atomic",
        common_scope_total=3,
        newly_satisfied=2,
        newly_satisfied_rate=0.75,
        out_of_scope_newly_satisfied=1,
        instances_judged=2,
        micro_newly_satisfied_rate=2 / 3,
        macro_newly_satisfied_rate=0.75,
        evaluated_in_scope=3,
        missing_in_scope=0,
        scoped_instance_count=2,
        zero_scope_instance_count=1,
        instance_scores=(
            fair_summary.FairInstanceScore(
                instance_id="100523",
                scope_total=2,
                evaluated_in_scope=2,
                missing_in_scope=0,
                newly_satisfied=1,
                newly_satisfied_rate=0.5,
                extra_newly_satisfied=1,
                existing_rule_satisfied=1,
                existing_rule_total=1,
                lost_existing_rules=0,
                eval_error=0,
            ),
            fair_summary.FairInstanceScore(
                instance_id="100951",
                scope_total=1,
                evaluated_in_scope=1,
                missing_in_scope=0,
                newly_satisfied=1,
                newly_satisfied_rate=1.0,
                extra_newly_satisfied=0,
                existing_rule_satisfied=0,
                existing_rule_total=1,
                lost_existing_rules=1,
                eval_error=0,
            ),
            fair_summary.FairInstanceScore(
                instance_id="100216",
                scope_total=0,
                evaluated_in_scope=0,
                missing_in_scope=0,
                newly_satisfied=0,
                newly_satisfied_rate=0.0,
                extra_newly_satisfied=0,
                existing_rule_satisfied=0,
                existing_rule_total=0,
                lost_existing_rules=0,
                eval_error=1,
            ),
        ),
    )
    report = compute_fair_report.FairReport(results_root=tmp_path, runs=(summary,))

    rendered = compute_fair_report.render_report(report)

    assert rendered == (
        "=== pilot_atomic ===\n"
        "PR      new_rules  lost_existing  extra_new  eval_error\n"
        "100523  1/2        0              1          0\n"
        "100951  1/1        1              0          0\n"
        "100216  -/0        0              0          1\n"
        "total   2/3        1              1          1\n"
    )
    assert "0.5" not in rendered
    assert "0.75" not in rendered
