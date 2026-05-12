"""Fair-summary aggregation that uses gold-derived scopes as denominators."""

import base
import judge


class FairInstanceScore(base.FrozenModel):
    """Per-instance score against gold-derived new/existing rule scopes."""

    instance_id: str
    scope_total: int
    evaluated_in_scope: int
    missing_in_scope: int
    newly_satisfied: int
    newly_satisfied_rate: float
    extra_newly_satisfied: int = 0
    existing_rule_satisfied: int = 0
    existing_rule_total: int = 0
    lost_existing_rules: int = 0
    eval_error: int = 0


class FairJudgmentSummary(base.FrozenModel):
    """Per-run summary computed against gold-derived scopes."""

    run_id: str
    common_scope_total: int
    newly_satisfied: int
    newly_satisfied_rate: float
    extra_newly_satisfied: int = 0
    out_of_scope_newly_satisfied: int
    instances_judged: int
    micro_newly_satisfied_rate: float = 0.0
    macro_newly_satisfied_rate: float = 0.0
    evaluated_in_scope: int = 0
    missing_in_scope: int = 0
    scoped_instance_count: int = 0
    zero_scope_instance_count: int = 0
    existing_rule_satisfied: int = 0
    existing_rule_total: int = 0
    lost_existing_rules: int = 0
    eval_error: int = 0
    instance_scores: tuple[FairInstanceScore, ...] = ()


def summarize_with_scope(
    *,
    run_id: str,
    run_judgments: tuple[judge.InstanceJudgment, ...],
    scope: dict[str, frozenset[str]],
    existing_scope: dict[str, frozenset[str]] | None = None,
) -> FairJudgmentSummary:
    """Aggregate strategy judgments with per-problem scoring."""
    existing_scope = existing_scope or {}
    judgments_by_instance = {instance.instance_id: instance for instance in run_judgments}
    instance_ids = tuple(sorted(set(scope) | set(existing_scope)))
    instance_scores = tuple(
        _score_instance(
            instance_id=instance_id,
            new_scope=scope.get(instance_id, frozenset()),
            existing_scope=existing_scope.get(instance_id, frozenset()),
            instance_judgment=judgments_by_instance.get(instance_id),
        )
        for instance_id in instance_ids
    )
    out_of_scope_newly_satisfied = _count_out_of_scope_newly_satisfied(
        run_judgments=run_judgments,
        scope=scope,
    )
    common_scope_total = sum(score.scope_total for score in instance_scores)
    newly_satisfied = sum(score.newly_satisfied for score in instance_scores)
    evaluated_in_scope = sum(score.evaluated_in_scope for score in instance_scores)
    missing_in_scope = sum(score.missing_in_scope for score in instance_scores)
    micro_rate = newly_satisfied / common_scope_total if common_scope_total else 0.0
    scoped_instance_scores = tuple(score for score in instance_scores if score.scope_total)
    macro_rate = _average(tuple(score.newly_satisfied_rate for score in scoped_instance_scores))
    return FairJudgmentSummary(
        run_id=run_id,
        common_scope_total=common_scope_total,
        newly_satisfied=newly_satisfied,
        newly_satisfied_rate=macro_rate,
        out_of_scope_newly_satisfied=out_of_scope_newly_satisfied,
        instances_judged=len(run_judgments),
        micro_newly_satisfied_rate=micro_rate,
        macro_newly_satisfied_rate=macro_rate,
        evaluated_in_scope=evaluated_in_scope,
        missing_in_scope=missing_in_scope,
        scoped_instance_count=len(scoped_instance_scores),
        zero_scope_instance_count=sum(1 for score in instance_scores if not score.scope_total),
        existing_rule_satisfied=sum(score.existing_rule_satisfied for score in instance_scores),
        existing_rule_total=sum(score.existing_rule_total for score in instance_scores),
        lost_existing_rules=sum(score.lost_existing_rules for score in instance_scores),
        eval_error=sum(score.eval_error for score in instance_scores),
        instance_scores=instance_scores,
    )


def _score_instance(
    *,
    instance_id: str,
    new_scope: frozenset[str],
    existing_scope: frozenset[str],
    instance_judgment: judge.InstanceJudgment | None,
) -> FairInstanceScore:
    judgments_by_constraint = _judgments_by_constraint(instance_judgment)
    evaluated_in_scope = sum(1 for constraint_id in new_scope if constraint_id in judgments_by_constraint)
    newly_satisfied = sum(
        1 for constraint_id in new_scope if _is_newly_satisfied(judgments_by_constraint.get(constraint_id))
    )
    scope_total = len(new_scope)
    return FairInstanceScore(
        instance_id=instance_id,
        scope_total=scope_total,
        evaluated_in_scope=evaluated_in_scope,
        missing_in_scope=scope_total - evaluated_in_scope,
        newly_satisfied=newly_satisfied,
        newly_satisfied_rate=newly_satisfied / scope_total if scope_total else 0.0,
        extra_newly_satisfied=_count_extra_newly_satisfied(judgments_by_constraint, new_scope),
        existing_rule_satisfied=_count_existing_rule_satisfied(judgments_by_constraint, existing_scope),
        existing_rule_total=len(existing_scope),
        lost_existing_rules=_count_lost_existing_rules(judgments_by_constraint, existing_scope),
        eval_error=_count_eval_errors(judgments_by_constraint),
    )


def _judgments_by_constraint(
    instance_judgment: judge.InstanceJudgment | None,
) -> dict[str, judge.ConstraintJudgment]:
    if instance_judgment is None:
        return {}
    return {judgment.constraint_id: judgment for judgment in instance_judgment.judgments}


def _count_out_of_scope_newly_satisfied(
    *,
    run_judgments: tuple[judge.InstanceJudgment, ...],
    scope: dict[str, frozenset[str]],
) -> int:
    count = 0
    for instance_judgment in run_judgments:
        in_scope = scope.get(instance_judgment.instance_id, frozenset())
        count += sum(
            1
            for judgment in instance_judgment.judgments
            if judgment.constraint_id not in in_scope and _is_newly_satisfied(judgment)
        )
    return count


def _count_extra_newly_satisfied(
    judgments_by_constraint: dict[str, judge.ConstraintJudgment],
    new_scope: frozenset[str],
) -> int:
    return sum(
        1
        for constraint_id, judgment in judgments_by_constraint.items()
        if constraint_id not in new_scope and _is_newly_satisfied(judgment)
    )


def _count_existing_rule_satisfied(
    judgments_by_constraint: dict[str, judge.ConstraintJudgment],
    existing_scope: frozenset[str],
) -> int:
    return sum(1 for constraint_id in existing_scope if _is_compliant(judgments_by_constraint.get(constraint_id)))


def _count_lost_existing_rules(
    judgments_by_constraint: dict[str, judge.ConstraintJudgment],
    existing_scope: frozenset[str],
) -> int:
    return sum(1 for constraint_id in existing_scope if _is_violated(judgments_by_constraint.get(constraint_id)))


def _count_eval_errors(judgments_by_constraint: dict[str, judge.ConstraintJudgment]) -> int:
    return sum(1 for judgment in judgments_by_constraint.values() if _is_eval_error(judgment))


def _is_newly_satisfied(judgment: judge.ConstraintJudgment | None) -> bool:
    if judgment is None:
        return False
    return (
        judgment.status == judge.JudgmentStatus.OK
        and judgment.verdict == judge.JudgeVerdict.COMPLIANT
        and judgment.patch_effect == judge.PatchEffect.APPLIED_BY_PATCH
    )


def _is_compliant(judgment: judge.ConstraintJudgment | None) -> bool:
    return (
        judgment is not None
        and judgment.status == judge.JudgmentStatus.OK
        and judgment.verdict == judge.JudgeVerdict.COMPLIANT
    )


def _is_violated(judgment: judge.ConstraintJudgment | None) -> bool:
    return (
        judgment is not None
        and judgment.status == judge.JudgmentStatus.OK
        and judgment.verdict == judge.JudgeVerdict.VIOLATED
    )


def _is_eval_error(judgment: judge.ConstraintJudgment) -> bool:
    return judgment.status != judge.JudgmentStatus.OK


def _average(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0
