"""Tests for dataset builder CLI helpers."""

from pathlib import Path

import build_dataset
import dataset_spec


def test_resolve_paths_resolves_all_dataset_spec_paths_relative_to_project_root(tmp_path: Path) -> None:
    spec = dataset_spec.DatasetSpec(
        github_repo="kubernetes/kubernetes",
        repo_path=Path("kubernetes"),
        target_paths=("api",),
        pr_search_labels=("kind/cleanup",),
        datasets_root=Path("datasets"),
        pr_cache_dir=Path("cache/pulls"),
        rejected_root=Path("datasets-rejected"),
    )

    resolved = build_dataset._resolve_paths(spec, tmp_path)

    assert resolved.repo_path == tmp_path / "kubernetes"
    assert resolved.datasets_root == tmp_path / "datasets"
    assert resolved.pr_cache_dir == tmp_path / "cache/pulls"
    assert resolved.rejected_root == tmp_path / "datasets-rejected"
