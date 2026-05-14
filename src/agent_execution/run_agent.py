"""CLI for running only the agent stage over a prebuilt dataset.

Usage:
    uv run python src/agent_execution/run_agent.py --spec config/experiment_spec_local_100.json
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import dataset_store  # noqa: E402
import experiment  # noqa: E402
import git_repository  # noqa: E402
import run_experiment  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run only agent execution over a prebuilt dataset.")
    parser.add_argument("--spec", type=Path, required=True, help="Path to the experiment spec JSON.")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--instance-id", action="append", default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    arguments = parse_args()
    spec = run_experiment._resolve_paths(experiment.load_experiment_spec(arguments.spec), arguments.project_root)
    git_repository.ensure_repository(spec.repo_path, "kubernetes/kubernetes")
    instances = run_experiment._select_instances(
        dataset_store.load_dataset_instances(spec.datasets_root),
        instance_ids=tuple(arguments.instance_id or ()),
        limit=arguments.limit if arguments.limit is not None else spec.instance_limit,
    )
    batches = experiment.run_agent_runs(spec, instances)
    for run_id, results in batches:
        completed = sum(1 for result in results if result.status == "completed")
        failed = sum(1 for result in results if result.status == "failed")
        skipped = sum(1 for result in results if result.status == "skipped")
        print(f"[agent/{run_id}] completed={completed} failed={failed} skipped={skipped}")


if __name__ == "__main__":
    main()
