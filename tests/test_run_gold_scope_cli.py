"""Tests for gold-scope CLI helpers."""

from pathlib import Path

import agent_runner
import client_spec
import dataset_builder
import experiment
import judge
import pr_collection
import run_gold_scope


def _make_instance(tmp_path: Path, pr_number: int) -> dataset_builder.DatasetInstance:
    detail = pr_collection.PullRequestDetail(
        pr_number=pr_number,
        base_sha="base",
        head_sha="head",
        title="Task",
        body="",
        labels=("kind/cleanup",),
        merged_at="2026-03-01T00:00:00Z",
        changed_files=("api/foo.go",),
        added_lines=1,
        deleted_lines=1,
    )
    return dataset_builder.DatasetInstance(detail=detail, root=tmp_path / str(pr_number))


def _experiment_spec_with_relative_paths() -> experiment.ExperimentSpec:
    return experiment.ExperimentSpec(
        datasets_root=Path("datasets"),
        results_root=Path("results"),
        repo_path=Path("kubernetes"),
        constraints_file=Path("constraints/api_conventions_atomic_constraints_73.json"),
        agent_configs=(
            agent_runner.AgentRunConfig(
                run_id="run-001",
                model="m",
                max_tokens=1024,
                context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
                docker=agent_runner.DockerAgentConfig(
                    image="k8s-bench-agent",
                    agent_command='agent run "$AGENT_PROMPT_PATH"',
                ),
            ),
        ),
        judge_config=judge.JudgeConfig(
            model="sonnet",
            max_tokens=256,
            system_prompt="judge",
            client=client_spec.ClientSpec(
                client_type=client_spec.ClientType.ANTHROPIC,
                api_key_env="JUDGE_KEY",
            ),
        ),
    )


def test_select_instances_filters_by_ids_before_limit(tmp_path: Path) -> None:
    instances = (
        _make_instance(tmp_path, 10),
        _make_instance(tmp_path, 20),
        _make_instance(tmp_path, 30),
    )

    selected = run_gold_scope._select_instances(
        instances,
        instance_ids=("30", "10"),
        limit=1,
    )

    assert tuple(instance.detail.pr_number for instance in selected) == (10,)


def test_resolve_paths_resolves_results_root_relative_to_project_root(tmp_path: Path) -> None:
    spec = _experiment_spec_with_relative_paths()

    resolved = run_gold_scope._resolve_paths(spec, tmp_path)

    assert resolved.datasets_root == tmp_path / "datasets"
    assert resolved.results_root == tmp_path / "results"
    assert resolved.repo_path == tmp_path / "kubernetes"
    assert resolved.constraints_file == tmp_path / "constraints/api_conventions_atomic_constraints_73.json"
