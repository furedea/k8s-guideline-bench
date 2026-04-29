"""Tests for dataset persistence / reload."""

import json
from pathlib import Path

import dataset_builder
import dataset_spec
import dataset_store
import error
import pytest


def _make_instance_on_disk(datasets_root: Path, pr_number: int) -> None:
    instance_root = datasets_root / str(pr_number)
    (instance_root / "base" / "api").mkdir(parents=True)
    (instance_root / "gold" / "api").mkdir(parents=True)
    _ = (instance_root / "base" / "api" / "foo.go").write_text("package api\n", encoding="utf-8")
    _ = (instance_root / "gold" / "api" / "foo.go").write_text("package v1\n", encoding="utf-8")
    _ = (instance_root / "gold_patch.diff").write_text(
        "diff --git a/api/foo.go b/api/foo.go\n",
        encoding="utf-8",
    )
    document = {
        "pr_number": pr_number,
        "base_sha": f"base-{pr_number}",
        "head_sha": f"head-{pr_number}",
        "title": "Refactor foo",
        "body": "",
        "labels": ["kind/cleanup"],
        "merged_at": "2026-03-01T00:00:00Z",
        "changed_files": ["api/foo.go"],
        "added_lines": 1,
        "deleted_lines": 0,
    }
    _ = (instance_root / "task.json").write_text(json.dumps(document), encoding="utf-8")


def test_load_dataset_instances_reads_all_task_metadata(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    _make_instance_on_disk(datasets_root, 1)
    _make_instance_on_disk(datasets_root, 2)

    instances = dataset_store.load_dataset_instances(datasets_root)

    pr_numbers = {instance.detail.pr_number for instance in instances}
    assert pr_numbers == {1, 2}
    assert all(isinstance(instance, dataset_builder.DatasetInstance) for instance in instances)
    assert all(instance.root.is_dir() for instance in instances)


def test_load_dataset_instances_sorted_by_directory_name_for_determinism(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    for pr_number in (30, 2, 11):
        _make_instance_on_disk(datasets_root, pr_number)

    instances = dataset_store.load_dataset_instances(datasets_root)

    # Sorted lexicographically by directory name: "11", "2", "30".
    assert [instance.root.name for instance in instances] == ["11", "2", "30"]


def test_load_dataset_instances_skips_non_instance_directories(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    _make_instance_on_disk(datasets_root, 7)
    (datasets_root / "_metadata").mkdir()
    _ = (datasets_root / "_metadata" / "notes.txt").write_text("ignore me", encoding="utf-8")

    instances = dataset_store.load_dataset_instances(datasets_root)

    assert len(instances) == 1
    assert instances[0].detail.pr_number == 7


def test_load_dataset_instances_raises_when_root_missing(tmp_path: Path) -> None:
    missing_root = tmp_path / "nowhere"

    with pytest.raises(error.ConstraintCatalogError, match="nowhere"):
        _ = dataset_store.load_dataset_instances(missing_root)


def test_load_dataset_instances_raises_on_malformed_task_json(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    (datasets_root / "123").mkdir(parents=True)
    _ = (datasets_root / "123" / "task.json").write_text("{not-valid}", encoding="utf-8")

    with pytest.raises(error.ConstraintCatalogError, match="123"):
        _ = dataset_store.load_dataset_instances(datasets_root)


def test_dataset_spec_coerces_path_and_target_paths() -> None:
    spec = dataset_spec.DatasetSpec(
        github_repo="kubernetes/kubernetes",
        repo_path="kubernetes",  # ty: ignore[invalid-argument-type]
        target_paths=["api"],  # ty: ignore[invalid-argument-type]
        pr_search_labels=["kind/cleanup"],  # ty: ignore[invalid-argument-type]
        datasets_root="datasets",  # ty: ignore[invalid-argument-type]
        pr_limit=5,
    )

    assert spec.repo_path == Path("kubernetes")
    assert spec.target_paths == ("api",)
    assert spec.since is None
    assert spec.pr_search_labels == ("kind/cleanup",)
    assert spec.datasets_root == Path("datasets")


def test_load_dataset_spec_parses_json(tmp_path: Path) -> None:
    spec_path = tmp_path / "dataset.json"
    _ = spec_path.write_text(
        json.dumps(
            {
                "github_repo": "kubernetes/kubernetes",
                "repo_path": "kubernetes",
                "target_paths": ["api", "pkg/apis"],
                "since": "2024-01-01",
                "pr_search_labels": ["kind/cleanup"],
                "datasets_root": "datasets",
                "pr_limit": 3,
            },
        ),
        encoding="utf-8",
    )

    loaded = dataset_spec.load_dataset_spec(spec_path)

    assert loaded.target_paths == ("api", "pkg/apis")
    assert loaded.pr_limit == 3


def test_load_dataset_spec_rejects_invalid_shape(tmp_path: Path) -> None:
    spec_path = tmp_path / "dataset.json"
    _ = spec_path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(error.ConstraintCatalogError):
        _ = dataset_spec.load_dataset_spec(spec_path)
