"""Tests for the end-to-end benchmark pipeline CLI helpers."""

import json
from pathlib import Path

import dataset_builder
import judge
from pytest_mock import MockerFixture

import run_benchmark


def _write_dataset_instance(root: Path, pr_number: int) -> Path:
    instance_root = root / str(pr_number)
    instance_root.mkdir(parents=True)
    _ = (instance_root / dataset_builder.TASK_FILENAME).write_text(
        json.dumps(
            {
                "pr_number": pr_number,
                "base_sha": "base",
                "head_sha": "head",
                "title": "Task",
                "body": "",
                "labels": ["kind/cleanup"],
                "merged_at": "2026-03-01T00:00:00Z",
                "changed_files": ["api/foo.go"],
                "added_lines": 1,
                "deleted_lines": 1,
            },
        ),
        encoding="utf-8",
    )
    _ = (instance_root / dataset_builder.GOLD_PATCH_FILENAME).write_text("diff --git\n", encoding="utf-8")
    return instance_root


def test_dataset_is_missing_when_root_has_no_instances(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    datasets_root.mkdir()

    assert run_benchmark.dataset_is_ready(datasets_root) is False


def test_dataset_is_ready_when_instances_have_gold_patches(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    _write_dataset_instance(datasets_root, 42)

    assert run_benchmark.dataset_is_ready(datasets_root) is True


def test_dataset_is_missing_when_any_instance_lacks_gold_patch(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    instance_root = _write_dataset_instance(datasets_root, 42)
    (instance_root / dataset_builder.GOLD_PATCH_FILENAME).unlink()

    assert run_benchmark.dataset_is_ready(datasets_root) is False


def test_gold_scope_is_ready_when_every_instance_has_judgments(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    results_root = tmp_path / "results"
    _write_dataset_instance(datasets_root, 42)
    _write_gold_scope_judgments(results_root, "42")

    assert run_benchmark.gold_scope_is_ready(datasets_root, results_root) is True


def test_gold_scope_is_missing_when_any_instance_lacks_judgments(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    results_root = tmp_path / "results"
    _write_dataset_instance(datasets_root, 42)

    assert run_benchmark.gold_scope_is_ready(datasets_root, results_root) is False


def test_fair_report_is_ready_when_report_file_exists(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    results_root.mkdir()
    _ = (results_root / "fair_report.json").write_text("{}", encoding="utf-8")

    assert run_benchmark.fair_report_is_ready(results_root) is True


def test_run_pipeline_skips_dataset_build_when_gold_patches_exist(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    datasets_root = tmp_path / "datasets"
    results_root = tmp_path / "results"
    repo_path = tmp_path / "kubernetes"
    constraints_file = tmp_path / "constraints.json"
    dataset_spec_path = tmp_path / "dataset.json"
    experiment_spec_path = tmp_path / "experiment.json"
    _write_dataset_instance(datasets_root, 42)
    _write_gold_scope_judgments(results_root, "42")
    _write_constraints(constraints_file)
    _write_dataset_spec(dataset_spec_path, datasets_root=datasets_root, repo_path=repo_path)
    _write_experiment_spec(
        experiment_spec_path,
        datasets_root=datasets_root,
        results_root=results_root,
        repo_path=repo_path,
        constraints_file=constraints_file,
    )
    build_dataset = mocker.patch("run_benchmark.dataset_builder.build_dataset_from_spec", autospec=True)
    run_experiment = mocker.patch("run_benchmark.experiment.run_experiment", autospec=True)
    compute_report = mocker.patch("run_benchmark.compute_fair_report.compute_fair_report", autospec=True)
    compute_report.return_value = run_benchmark.compute_fair_report.FairReport(results_root=results_root, runs=())
    _ = mocker.patch("run_benchmark.compute_fair_report.render_report", autospec=True, return_value="")
    _ = mocker.patch("run_benchmark.git_repository.ensure_repository", autospec=True)

    run_benchmark.run_pipeline(
        dataset_spec_path=dataset_spec_path,
        experiment_spec_path=experiment_spec_path,
        project_root=tmp_path,
    )

    build_dataset.assert_not_called()
    run_experiment.assert_called_once()
    compute_report.assert_called_once()


def _write_gold_scope_judgments(results_root: Path, instance_id: str) -> None:
    instance_dir = results_root / "gold_scope" / instance_id
    instance_dir.mkdir(parents=True)
    result = judge.InstanceJudgment(
        instance_id=instance_id,
        run_id="gold_scope",
        judgments=(),
    )
    _ = (instance_dir / "judgments.json").write_text(
        json.dumps(result.model_dump(mode="json")),
        encoding="utf-8",
    )


def _write_constraints(path: Path) -> None:
    _ = path.write_text(
        json.dumps(
            [
                {
                    "id": "atom_001",
                    "normative_source_ids": ["norm_001"],
                    "source_path": "docs/source/api-conventions.md",
                    "source_span": "1-1",
                    "title": "Rule",
                    "rule": "Use the rule.",
                    "rationale": "Consistency.",
                    "judgeability": "machine_checkable",
                },
            ],
        ),
        encoding="utf-8",
    )


def _write_dataset_spec(path: Path, *, datasets_root: Path, repo_path: Path) -> None:
    _ = path.write_text(
        json.dumps(
            {
                "github_repo": "kubernetes/kubernetes",
                "repo_path": str(repo_path),
                "target_paths": ["api/"],
                "exclusion_patterns": [],
                "since": None,
                "model_cutoffs": {},
                "pr_search_labels": ["kind/cleanup"],
                "required_pr_labels": ["kind/cleanup"],
                "excluded_pr_labels": [],
                "pr_search_window_days": 30,
                "pr_search_limit": 1000,
                "pr_search_until": None,
                "pr_cache_dir": str(path.parent / "cache"),
                "min_changed_files": 1,
                "min_changed_lines": 1,
                "max_changed_files": None,
                "max_changed_lines": None,
                "verification_level": "none",
                "rejected_root": None,
                "pr_limit": None,
                "datasets_root": str(datasets_root),
            },
        ),
        encoding="utf-8",
    )


def _write_experiment_spec(
    path: Path,
    *,
    datasets_root: Path,
    results_root: Path,
    repo_path: Path,
    constraints_file: Path,
) -> None:
    _ = path.write_text(
        json.dumps(
            {
                "datasets_root": str(datasets_root),
                "results_root": str(results_root),
                "repo_path": str(repo_path),
                "constraints_file": str(constraints_file),
                "agent_configs": [
                    {
                        "run_id": "run-001",
                        "model": "agent",
                        "max_tokens": 1024,
                        "context_strategy": "no_constraints",
                        "docker": {
                            "image": "k8s-bench-agent",
                            "agent_command": "agent",
                        },
                    },
                ],
                "judge_config": {
                    "model": "judge",
                    "max_tokens": 256,
                    "system_prompt": "judge",
                    "client": {
                        "client_type": "claude_cli",
                    },
                    "skip_existing": True,
                },
            },
        ),
        encoding="utf-8",
    )
