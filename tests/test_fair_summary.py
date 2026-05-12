"""Tests for fair-summary aggregation that uses the gold scope as the denominator."""

import fair_summary
import judge
import pytest


def _instance_judgment(
    instance_id: str,
    run_id: str,
    judgments: tuple[judge.ConstraintJudgment, ...],
) -> judge.InstanceJudgment:
    return judge.InstanceJudgment(instance_id=instance_id, run_id=run_id, judgments=judgments)


def _compliant_applied(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="",
        patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
    )


def _compliant_already(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="",
        patch_effect=judge.PatchEffect.ALREADY_SATISFIED,
    )


def _violated(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        verdict=judge.JudgeVerdict.VIOLATED,
        confidence=0.8,
        rationale="",
    )


def _not_applicable(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        verdict=judge.JudgeVerdict.NOT_APPLICABLE,
        confidence=0.5,
        rationale="",
    )


def _api_failure(constraint_id: str) -> judge.ConstraintJudgment:
    return judge.ConstraintJudgment(
        constraint_id=constraint_id,
        status=judge.JudgmentStatus.API_FAILURE,
        verdict=judge.JudgeVerdict.NOT_APPLICABLE,
        confidence=0.0,
        rationale="boom",
    )


def test_summarize_with_scope_uses_gold_scope_as_denominator() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot_no_constraints",
            (
                _compliant_applied("c1"),
                _compliant_already("c2"),
                _violated("c3"),
            ),
        ),
    )
    scope = {"42": frozenset({"c1", "c2", "c3"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot_no_constraints",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.run_id == "pilot_no_constraints"
    assert summary.common_scope_total == 3
    assert summary.scoped_instance_count == 1
    assert summary.zero_scope_instance_count == 0
    assert summary.evaluated_in_scope == 3
    assert summary.missing_in_scope == 0
    assert summary.newly_satisfied == 1
    assert summary.micro_newly_satisfied_rate == pytest.approx(1 / 3)
    assert summary.macro_newly_satisfied_rate == pytest.approx(1 / 3)
    assert summary.newly_satisfied_rate == pytest.approx(1 / 3)
    assert summary.out_of_scope_newly_satisfied == 0
    assert summary.instances_judged == 1
    assert summary.instance_scores[0].instance_id == "42"
    assert summary.instance_scores[0].newly_satisfied_rate == pytest.approx(1 / 3)
    assert summary.instance_scores[0].extra_newly_satisfied == 0


def test_summarize_with_scope_excludes_out_of_scope_constraints_from_denominator() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot_atomic",
            (
                _compliant_applied("c1"),
                _compliant_applied("c2"),
            ),
        ),
    )
    scope = {"42": frozenset({"c1"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot_atomic",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.common_scope_total == 1
    assert summary.newly_satisfied == 1
    assert summary.out_of_scope_newly_satisfied == 1
    assert summary.instance_scores[0].extra_newly_satisfied == 1
    assert summary.micro_newly_satisfied_rate == 1.0
    assert summary.macro_newly_satisfied_rate == 1.0


def test_summarize_with_scope_treats_strategy_not_applicable_as_zero_numerator() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot_no_constraints",
            (
                _not_applicable("c1"),
                _violated("c2"),
            ),
        ),
    )
    scope = {"42": frozenset({"c1", "c2"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot_no_constraints",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.common_scope_total == 2
    assert summary.newly_satisfied == 0
    assert summary.micro_newly_satisfied_rate == 0.0
    assert summary.macro_newly_satisfied_rate == 0.0
    assert summary.newly_satisfied_rate == 0.0


def test_summarize_with_scope_ignores_already_satisfied_in_numerator() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot",
            (_compliant_already("c1"),),
        ),
    )
    scope = {"42": frozenset({"c1"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.newly_satisfied == 0
    assert summary.common_scope_total == 1
    assert summary.micro_newly_satisfied_rate == 0.0
    assert summary.macro_newly_satisfied_rate == 0.0


def test_summarize_with_scope_uses_empty_scope_for_unknown_instances() -> None:
    run_judgments = (
        _instance_judgment(
            "99",
            "pilot",
            (_compliant_applied("c1"),),
        ),
    )

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope={},
    )

    assert summary.common_scope_total == 0
    assert summary.newly_satisfied == 0
    assert summary.micro_newly_satisfied_rate == 0.0
    assert summary.macro_newly_satisfied_rate == 0.0
    assert summary.newly_satisfied_rate == 0.0
    assert summary.out_of_scope_newly_satisfied == 1


def test_summarize_with_scope_records_extra_hits_per_problem() -> None:
    run_judgments = (
        _instance_judgment("42", "pilot", (_compliant_applied("c1"), _compliant_applied("c2"))),
        _instance_judgment("43", "pilot", (_compliant_applied("c3"),)),
    )
    scope = {
        "42": frozenset({"c1"}),
        "43": frozenset({"c4"}),
    }

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.out_of_scope_newly_satisfied == 2
    assert tuple(score.extra_newly_satisfied for score in summary.instance_scores) == (1, 1)


def test_summarize_with_scope_aggregates_multiple_instances() -> None:
    run_judgments = (
        _instance_judgment("42", "pilot", (_compliant_applied("c1"), _violated("c2"))),
        _instance_judgment("43", "pilot", (_compliant_applied("c3"),)),
    )
    scope = {
        "42": frozenset({"c1", "c2"}),
        "43": frozenset({"c3"}),
    }

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.common_scope_total == 3
    assert summary.newly_satisfied == 2
    assert summary.micro_newly_satisfied_rate == pytest.approx(2 / 3)
    assert summary.macro_newly_satisfied_rate == pytest.approx((1 / 2 + 1) / 2)
    assert summary.instances_judged == 2


def test_summarize_with_scope_counts_failures_against_denominator_but_not_numerator() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot",
            (_api_failure("c1"), _compliant_applied("c2")),
        ),
    )
    scope = {"42": frozenset({"c1", "c2"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.common_scope_total == 2
    assert summary.evaluated_in_scope == 2
    assert summary.missing_in_scope == 0
    assert summary.newly_satisfied == 1
    assert summary.micro_newly_satisfied_rate == 0.5
    assert summary.macro_newly_satisfied_rate == 0.5
    assert summary.eval_error == 1
    assert summary.instance_scores[0].eval_error == 1


def test_summarize_with_scope_uses_per_problem_macro_average() -> None:
    run_judgments = (
        _instance_judgment("a", "pilot", (_compliant_applied("c1"),)),
        _instance_judgment("b", "pilot", (_compliant_applied("c1"), _violated("c2"), _violated("c3"))),
    )
    scope = {
        "a": frozenset({"c1"}),
        "b": frozenset({"c1", "c2", "c3"}),
    }

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.micro_newly_satisfied_rate == pytest.approx(2 / 4)
    assert summary.macro_newly_satisfied_rate == pytest.approx((1 + 1 / 3) / 2)
    assert summary.newly_satisfied_rate == summary.macro_newly_satisfied_rate


def test_summarize_with_scope_keeps_missing_strategy_judgments_in_denominator() -> None:
    run_judgments = (_instance_judgment("a", "pilot", (_compliant_applied("c1"),)),)
    scope = {
        "a": frozenset({"c1"}),
        "b": frozenset({"c1", "c2"}),
    }

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.common_scope_total == 3
    assert summary.evaluated_in_scope == 1
    assert summary.missing_in_scope == 2
    assert summary.scoped_instance_count == 2
    assert summary.instances_judged == 1
    assert summary.micro_newly_satisfied_rate == pytest.approx(1 / 3)
    assert summary.macro_newly_satisfied_rate == pytest.approx((1 + 0) / 2)
    assert tuple(score.instance_id for score in summary.instance_scores) == ("a", "b")
    assert summary.instance_scores[1].missing_in_scope == 2
    assert summary.instance_scores[1].newly_satisfied_rate == 0.0


def test_summarize_with_scope_excludes_zero_scope_instances_from_macro_average() -> None:
    run_judgments = (_instance_judgment("a", "pilot", (_compliant_applied("c1"),)),)
    scope = {
        "a": frozenset({"c1"}),
        "empty": frozenset(),
    }

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
    )

    assert summary.scoped_instance_count == 1
    assert summary.zero_scope_instance_count == 1
    assert summary.common_scope_total == 1
    assert summary.macro_newly_satisfied_rate == 1.0
    assert tuple(score.instance_id for score in summary.instance_scores) == ("a", "empty")
    assert summary.instance_scores[1].scope_total == 0


def test_summarize_with_scope_reports_existing_violations_as_lost_existing() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot",
            (
                _compliant_applied("new1"),
                _compliant_already("old1"),
                _violated("old2"),
            ),
        ),
    )
    scope = {"42": frozenset({"new1"})}
    existing_scope = {"42": frozenset({"old1", "old2"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
        existing_scope=existing_scope,
    )

    score = summary.instance_scores[0]
    assert score.newly_satisfied == 1
    assert score.existing_rule_satisfied == 1
    assert score.existing_rule_total == 2
    assert score.lost_existing_rules == 1
    assert summary.existing_rule_satisfied == 1
    assert summary.existing_rule_total == 2
    assert summary.lost_existing_rules == 1


def test_summarize_with_scope_does_not_count_not_applicable_existing_rules_as_lost() -> None:
    run_judgments = (
        _instance_judgment(
            "42",
            "pilot",
            (
                _compliant_already("old1"),
                _not_applicable("old2"),
            ),
        ),
    )
    scope = {"42": frozenset()}
    existing_scope = {"42": frozenset({"old1", "old2"})}

    summary = fair_summary.summarize_with_scope(
        run_id="pilot",
        run_judgments=run_judgments,
        scope=scope,
        existing_scope=existing_scope,
    )

    score = summary.instance_scores[0]
    assert score.existing_rule_satisfied == 1
    assert score.existing_rule_total == 2
    assert score.lost_existing_rules == 0
    assert score.eval_error == 0
    assert summary.lost_existing_rules == 0
    assert summary.eval_error == 0
