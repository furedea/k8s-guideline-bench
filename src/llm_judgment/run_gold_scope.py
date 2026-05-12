"""CLI for computing per-PR gold improvement scope for fair summaries.

Usage:
    uv run python src/llm_judgment/run_gold_scope.py --spec config/experiment_spec_pilot.json

Reads an existing ``ExperimentSpec`` and judges every dataset instance's gold
patch under ``PATCH_ONLY`` mode using ``spec.gold_scope_judge_config`` (defaults
to the strategy judge model). The persisted judgments land under
``<results_root>/gold_scope/<instance>/judgments.json``; constraints with
``patch_effect=applied_by_patch`` form the fair-summary denominator. Run this
once before ``compute_fair_report`` so the fair denominator is available.
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import atomic_constraint  # noqa: E402
import completion_client_factory  # noqa: E402
import dataset_builder  # noqa: E402
import dataset_store  # noqa: E402
import experiment  # noqa: E402
import git_repository  # noqa: E402
import gold_scope  # noqa: E402
import project_paths  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the gold-scope runner."""
    parser = argparse.ArgumentParser(
        description="Judge gold patches to define the fair-summary improvement denominator."
    )
    _ = parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to the experiment spec JSON.",
    )
    _ = parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Project root used to resolve relative paths in the spec.",
    )
    _ = parser.add_argument(
        "--instance-id",
        action="append",
        default=None,
        help="Dataset PR number to scope. Repeat to run multiple specific instances.",
    )
    _ = parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of selected dataset instances to scope.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: load spec + dataset → judge gold patches → persist scope."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_args()
    spec = experiment.load_experiment_spec(arguments.spec)
    resolved_spec = _resolve_paths(spec, arguments.project_root)
    git_repository.ensure_repository(resolved_spec.repo_path, "kubernetes/kubernetes")
    instances = _select_instances(
        dataset_store.load_dataset_instances(resolved_spec.datasets_root),
        instance_ids=tuple(arguments.instance_id or ()),
        limit=arguments.limit if arguments.limit is not None else resolved_spec.instance_limit,
    )
    constraints = atomic_constraint.load_atomic_constraints(resolved_spec.constraints_file)
    gold_patches = tuple(_load_gold_patch(instance) for instance in instances)
    gold_judge_config = resolved_spec.gold_scope_judge_config
    assert gold_judge_config is not None, "ExperimentSpec post-init validator populates this default."
    client = completion_client_factory.build_completion_client(gold_judge_config.client)
    results = gold_scope.judge_gold_scope(
        instances=instances,
        gold_patches=gold_patches,
        constraints=constraints,
        client=client,
        config=gold_judge_config,
        results_root=resolved_spec.results_root,
    )
    for result in results:
        gold_hits = sum(1 for judgment in result.judgments if gold_scope.is_in_scope(judgment))
        print(f"[gold_scope/{result.instance_id}] gold_hits={gold_hits}/{len(result.judgments)}")


def _select_instances(
    instances: tuple[dataset_builder.DatasetInstance, ...],
    instance_ids: tuple[str, ...],
    limit: int | None,
) -> tuple[dataset_builder.DatasetInstance, ...]:
    selected = instances
    if instance_ids:
        selected_ids = set(instance_ids)
        selected = tuple(instance for instance in selected if str(instance.detail.pr_number) in selected_ids)
    if limit is not None:
        selected = selected[:limit]
    return selected


def _resolve_paths(
    spec: experiment.ExperimentSpec,
    project_root: Path,
) -> experiment.ExperimentSpec:
    return spec.model_copy(
        update={
            "datasets_root": project_paths.resolve_under(project_root, spec.datasets_root),
            "results_root": project_paths.resolve_under(project_root, spec.results_root),
            "repo_path": project_paths.resolve_under(project_root, spec.repo_path),
            "constraints_file": project_paths.resolve_under(project_root, spec.constraints_file),
        },
    )


def _load_gold_patch(instance: dataset_builder.DatasetInstance) -> str:
    gold_patch_path = instance.root / dataset_builder.GOLD_PATCH_FILENAME
    try:
        return gold_patch_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


if __name__ == "__main__":
    main()
