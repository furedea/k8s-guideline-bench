"""CLI for judging existing agent artifacts.

Usage:
    uv run python src/llm_judgment/run_judgment.py --spec config/experiment_spec_local_100.json
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import completion_client_factory  # noqa: E402
import dataset_store  # noqa: E402
import experiment  # noqa: E402
import run_experiment  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run only LLM judgment over existing agent results.")
    parser.add_argument("--spec", type=Path, required=True, help="Path to the experiment spec JSON.")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--instance-id", action="append", default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_args()
    spec = run_experiment._resolve_paths(experiment.load_experiment_spec(arguments.spec), arguments.project_root)
    instances = run_experiment._select_instances(
        dataset_store.load_dataset_instances(spec.datasets_root),
        instance_ids=tuple(arguments.instance_id or ()),
        limit=arguments.limit if arguments.limit is not None else spec.instance_limit,
    )
    report = experiment.run_judgment(
        spec,
        instances,
        client_factory=completion_client_factory.build_completion_client,
    )
    for run in report.runs:
        print(
            f"[judge/{run.run_id}] judged={run.instances_judged} "
            f"api_failure={run.instances_with_api_failure} total={run.summary.total}",
        )


if __name__ == "__main__":
    main()
