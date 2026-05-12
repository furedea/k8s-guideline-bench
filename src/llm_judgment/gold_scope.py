"""Gold-patch scoping: define per-PR improvement opportunities from the human patch.

The strategy-side judge decides applicability after seeing the predicted patch,
so each strategy can get a different denominator. Judging the human gold patch
once in ``PATCH_ONLY`` mode gives a strategy-independent improvement scope:
constraints that the human patch newly satisfied. ``fair_summary`` consumes the
persisted scope as the shared comparison target across every strategy.
"""

from collections.abc import Callable
from pathlib import Path

import atomic_constraint
import completion_client
import dataset_builder
import judge
import tqdm

GOLD_SCOPE_RUN_ID = "gold_scope"


def judge_gold_scope(
    *,
    instances: tuple[dataset_builder.DatasetInstance, ...],
    gold_patches: tuple[str, ...],
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    client: completion_client.CompletionClient,
    config: judge.JudgeConfig,
    results_root: Path,
) -> tuple[judge.InstanceJudgment, ...]:
    """Judge every instance's gold patch under ``PATCH_ONLY`` mode.

    Each call delegates to ``judge.judge_instance`` with the gold patch fed as
    ``predicted_patch`` and an empty ``gold_patch``. The persisted
    ``judgments.json`` lands under ``<results_root>/gold_scope/<instance>/``,
    making the scope reusable by ``load_gold_scope``.
    """
    progress = tqdm.tqdm(
        zip(instances, gold_patches, strict=True),
        desc=f"judge[{GOLD_SCOPE_RUN_ID}]",
        unit="pr",
        ncols=88,
        total=len(instances),
    )
    return tuple(
        judge.judge_instance(
            instance=instance,
            predicted_patch=gold_patch,
            gold_patch="",
            constraints=constraints,
            client=client,
            config=config,
            run_id=GOLD_SCOPE_RUN_ID,
            results_root=results_root,
        )
        for instance, gold_patch in progress
    )


def is_in_scope(judgment: judge.ConstraintJudgment) -> bool:
    """Return whether the gold patch newly satisfied this constraint."""
    return (
        judgment.status == judge.JudgmentStatus.OK
        and judgment.verdict == judge.JudgeVerdict.COMPLIANT
        and judgment.patch_effect == judge.PatchEffect.APPLIED_BY_PATCH
    )


def load_existing_rule_scope(results_root: Path) -> dict[str, frozenset[str]]:
    """Load gold rules that were already satisfied before the human patch."""
    return _load_scope_by_predicate(results_root, is_existing_rule)


def is_existing_rule(judgment: judge.ConstraintJudgment) -> bool:
    """Return whether the gold patch found this rule already satisfied."""
    return (
        judgment.status == judge.JudgmentStatus.OK
        and judgment.verdict == judge.JudgeVerdict.COMPLIANT
        and judgment.patch_effect == judge.PatchEffect.ALREADY_SATISFIED
    )


def load_gold_scope(results_root: Path) -> dict[str, frozenset[str]]:
    """Load gold rules newly satisfied by the human patch."""
    return _load_scope_by_predicate(results_root, is_in_scope)


def _load_scope_by_predicate(
    results_root: Path,
    predicate: Callable[[judge.ConstraintJudgment], bool],
) -> dict[str, frozenset[str]]:
    scope_root = results_root / GOLD_SCOPE_RUN_ID
    if not scope_root.is_dir():
        return {}
    scope: dict[str, frozenset[str]] = {}
    for instance_dir in sorted(scope_root.iterdir()):
        if not instance_dir.is_dir():
            continue
        if not (instance_dir / "judgments.json").is_file():
            continue
        judgments = judge.load_instance_judgments(results_root, GOLD_SCOPE_RUN_ID, instance_dir.name)
        scope[instance_dir.name] = frozenset(j.constraint_id for j in judgments if predicate(j))
    return scope
