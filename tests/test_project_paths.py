from pathlib import Path

import project_paths


def test_project_paths_resolves_repository_directories() -> None:
    repository_root = Path("/tmp/k8s-guideline-bench")

    paths = project_paths.ProjectPaths.from_root(repository_root)

    assert paths.root == repository_root
    assert paths.constraints_file == repository_root / "constraints" / "atomic_constraints.json"
    assert paths.config_directory == repository_root / "config"
    assert paths.datasets_directory == repository_root / "datasets"
    assert paths.results_directory == repository_root / "results"
