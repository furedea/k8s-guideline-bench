"""End-to-end benchmark pipeline CLI.

Usage:
    uv run python src/run_benchmark.py \
      --dataset-spec config/dataset_spec.json \
      --experiment-spec config/experiment_spec_local_100.json
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import atomic_constraint  # noqa: E402
import completion_client_factory  # noqa: E402
import compute_fair_report  # noqa: E402
import dataset_builder  # noqa: E402
import dataset_spec as dataset_spec_module  # noqa: E402
import dataset_store  # noqa: E402
import experiment  # noqa: E402
import git_repository  # noqa: E402
import gold_scope  # noqa: E402
import project_paths  # noqa: E402
import run_experiment  # noqa: E402
import run_gold_scope  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the dataset → agent → judge → fair-report pipeline.")
    parser.add_argument("--dataset-spec", type=Path, required=True, help="Path to the dataset spec JSON.")
    parser.add_argument("--experiment-spec", type=Path, required=True, help="Path to the experiment spec JSON.")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--instance-id", action="append", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-dataset", action="store_true")
    parser.add_argument("--skip-gold-scope", action="store_true")
    parser.add_argument("--skip-agent-judge", action="store_true")
    parser.add_argument("--skip-report", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_args()
    run_pipeline(
        dataset_spec_path=arguments.dataset_spec,
        experiment_spec_path=arguments.experiment_spec,
        project_root=arguments.project_root,
        instance_ids=tuple(arguments.instance_id or ()),
        limit=arguments.limit,
        skip_dataset=arguments.skip_dataset,
        skip_gold_scope=arguments.skip_gold_scope,
        skip_agent_judge=arguments.skip_agent_judge,
        skip_report=arguments.skip_report,
    )


def run_pipeline(
    *,
    dataset_spec_path: Path,
    experiment_spec_path: Path,
    project_root: Path,
    instance_ids: tuple[str, ...] = (),
    limit: int | None = None,
    skip_dataset: bool = False,
    skip_gold_scope: bool = False,
    skip_agent_judge: bool = False,
    skip_report: bool = False,
) -> None:
    dataset_spec = _resolve_dataset_spec(dataset_spec_module.load_dataset_spec(dataset_spec_path), project_root)
    experiment_spec = run_experiment._resolve_paths(
        experiment.load_experiment_spec(experiment_spec_path), project_root
    )

    git_repository.ensure_repository(dataset_spec.repo_path, dataset_spec.github_repo)
    git_repository.ensure_repository(experiment_spec.repo_path, "kubernetes/kubernetes")

    if not skip_dataset and not dataset_is_ready(experiment_spec.datasets_root):
        _ = dataset_builder.build_dataset_from_spec(dataset_spec)

    instances = _select_instances(experiment_spec.datasets_root, instance_ids=instance_ids, limit=limit)
    if not skip_gold_scope and not gold_scope_is_ready_for_instances(instances, experiment_spec.results_root):
        _run_gold_scope(experiment_spec, instances)

    if not skip_agent_judge:
        _ = experiment.run_experiment(
            experiment_spec,
            instances,
            client_factory=completion_client_factory.build_completion_client,
        )

    if not skip_report:
        run_ids = tuple(agent_config.run_id for agent_config in experiment_spec.agent_configs)
        report = compute_fair_report.compute_fair_report(results_root=experiment_spec.results_root, run_ids=run_ids)
        print(compute_fair_report.render_report(report), end="")


def dataset_is_ready(datasets_root: Path) -> bool:
    if not datasets_root.is_dir():
        return False
    instance_roots = tuple(
        child for child in datasets_root.iterdir() if (child / dataset_builder.TASK_FILENAME).is_file()
    )
    return bool(instance_roots) and all(
        (instance_root / dataset_builder.GOLD_PATCH_FILENAME).is_file() for instance_root in instance_roots
    )


def gold_scope_is_ready(datasets_root: Path, results_root: Path) -> bool:
    if not datasets_root.is_dir():
        return False
    instances = dataset_store.load_dataset_instances(datasets_root)
    return gold_scope_is_ready_for_instances(instances, results_root)


def gold_scope_is_ready_for_instances(
    instances: tuple[dataset_builder.DatasetInstance, ...],
    results_root: Path,
) -> bool:
    if not instances:
        return False
    return all(
        (results_root / gold_scope.GOLD_SCOPE_RUN_ID / str(instance.detail.pr_number) / "judgments.json").is_file()
        for instance in instances
    )


def fair_report_is_ready(results_root: Path) -> bool:
    return (results_root / "fair_report.json").is_file()


def _run_gold_scope(
    spec: experiment.ExperimentSpec,
    instances: tuple[dataset_builder.DatasetInstance, ...],
) -> None:
    constraints = atomic_constraint.load_atomic_constraints(spec.constraints_file)
    gold_patches = tuple(run_gold_scope._load_gold_patch(instance) for instance in instances)
    gold_judge_config = spec.gold_scope_judge_config
    assert gold_judge_config is not None, "ExperimentSpec post-init validator populates this default."
    client = completion_client_factory.build_completion_client(gold_judge_config.client)
    _ = gold_scope.judge_gold_scope(
        instances=instances,
        gold_patches=gold_patches,
        constraints=constraints,
        client=client,
        config=gold_judge_config,
        results_root=spec.results_root,
    )


def _select_instances(
    datasets_root: Path,
    *,
    instance_ids: tuple[str, ...],
    limit: int | None,
) -> tuple[dataset_builder.DatasetInstance, ...]:
    return run_experiment._select_instances(
        dataset_store.load_dataset_instances(datasets_root),
        instance_ids=instance_ids,
        limit=limit,
    )


def _resolve_dataset_spec(
    spec: dataset_spec_module.DatasetSpec,
    project_root: Path,
) -> dataset_spec_module.DatasetSpec:
    return spec.model_copy(
        update={
            "repo_path": project_paths.resolve_under(project_root, spec.repo_path),
            "datasets_root": project_paths.resolve_under(project_root, spec.datasets_root),
            "pr_cache_dir": _resolve_optional_path(project_root, spec.pr_cache_dir),
            "rejected_root": _resolve_optional_path(project_root, spec.rejected_root),
        },
    )


def _resolve_optional_path(project_root: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return project_paths.resolve_under(project_root, path)


if __name__ == "__main__":
    main()
