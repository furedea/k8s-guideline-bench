"""CLI for running agent + judge experiments over a prebuilt dataset.

Usage:
    uv run python src/llm_judgment/run_experiment.py --spec config/experiment_spec_pilot.json
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import agent_runner  # noqa: E402
import completion_client_factory  # noqa: E402
import dataset_builder  # noqa: E402
import dataset_store  # noqa: E402
import experiment  # noqa: E402
import git_repository  # noqa: E402
import project_paths  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the experiment runner."""
    parser = argparse.ArgumentParser(description="Run experiments over a prebuilt dataset.")
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
        help="Dataset PR number to run. Repeat to run multiple specific instances.",
    )
    _ = parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of selected dataset instances to run.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: load spec + dataset → run agent → judge → report."""
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
    report = experiment.run_experiment(
        resolved_spec,
        instances,
        client_factory=completion_client_factory.build_completion_client,
    )
    for run in report.runs:
        print(
            f"[{run.run_id}] model={run.model} strategy={run.context_strategy.value} "
            f"newly_satisfied={run.summary.newly_satisfied_rate:.3f} "
            f"applied={run.summary.newly_satisfied}/{run.summary.effective_total} "
            f"compliance={run.summary.compliance_rate:.3f}",
        )


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
            "agent_configs": tuple(_resolve_agent_config(project_root, config) for config in spec.agent_configs),
        },
    )


def _resolve_agent_config(
    project_root: Path,
    config: agent_runner.AgentRunConfig,
) -> agent_runner.AgentRunConfig:
    return config.model_copy(
        update={
            "context_files": tuple(
                context_file.model_copy(
                    update={"source_path": project_paths.resolve_under(project_root, context_file.source_path)},
                )
                for context_file in config.context_files
            ),
        },
    )


if __name__ == "__main__":
    main()
