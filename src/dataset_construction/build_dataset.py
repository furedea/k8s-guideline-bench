"""CLI for materializing the benchmark dataset from a git repository.

Usage:
    uv run python src/dataset_construction/build_dataset.py --spec config/dataset_spec.json
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import dataset_builder  # noqa: E402
import dataset_spec as dataset_spec_module  # noqa: E402
import git_repository  # noqa: E402
import project_paths  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the dataset builder."""
    parser = argparse.ArgumentParser(description="Build the benchmark dataset.")
    _ = parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to the dataset spec JSON.",
    )
    _ = parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Project root used to resolve relative paths in the spec.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: load spec → materialize dataset on disk."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    arguments = parse_args()
    spec = dataset_spec_module.load_dataset_spec(arguments.spec)
    resolved_spec = _resolve_paths(spec, arguments.project_root)
    git_repository.ensure_repository(resolved_spec.repo_path, resolved_spec.github_repo)

    instances = dataset_builder.build_dataset_from_spec(resolved_spec)
    print(
        f"Built {len(instances)} dataset instance(s) under {resolved_spec.datasets_root}",
    )


def _resolve_paths(
    spec: dataset_spec_module.DatasetSpec,
    project_root: Path,
) -> dataset_spec_module.DatasetSpec:
    return spec.model_copy(
        update={
            "repo_path": project_paths.resolve_under(project_root, spec.repo_path),
            "datasets_root": project_paths.resolve_under(project_root, spec.datasets_root),
        },
    )


if __name__ == "__main__":
    main()
