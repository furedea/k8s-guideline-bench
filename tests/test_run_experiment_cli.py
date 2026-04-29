"""Tests for experiment CLI helpers."""

from pathlib import Path

import agent_runner
import client_spec
import dataset_builder
import experiment
import judge
import pr_collection
import run_experiment


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


def test_select_instances_filters_by_ids_before_limit(tmp_path: Path) -> None:
    instances = (
        _make_instance(tmp_path, 10),
        _make_instance(tmp_path, 20),
        _make_instance(tmp_path, 30),
    )

    selected = run_experiment._select_instances(
        instances,
        instance_ids=("30", "10"),
        limit=1,
    )

    assert tuple(instance.detail.pr_number for instance in selected) == (10,)


def test_resolve_paths_resolves_repo_and_context_files(tmp_path: Path) -> None:
    spec = experiment.ExperimentSpec(
        datasets_root=Path("datasets"),
        results_root=Path("results"),
        repo_path=Path("kubernetes"),
        constraints_file=Path("constraints/api_conventions_atomic_constraints_73.json"),
        instance_limit=10,
        agent_configs=(
            agent_runner.AgentRunConfig(
                run_id="pilot",
                model="opencode-go/deepseek-v4-flash",
                max_tokens=8192,
                context_strategy=agent_runner.ContextStrategy.API_CONVENTIONS_MD,
                docker=agent_runner.DockerAgentConfig(
                    image="k8s-bench-agent",
                    agent_command='opencode run --model "$MODEL" < "$AGENT_PROMPT_PATH"',
                ),
                context_files=(
                    agent_runner.AttachedContextFile(
                        source_path=Path("docs/source/api-conventions.md"),
                        bench_path="api-conventions.md",
                        description="Kubernetes API conventions source document.",
                    ),
                ),
            ),
        ),
        judge_config=judge.JudgeConfig(
            model="judge",
            max_tokens=256,
            system_prompt="judge",
            client=client_spec.ClientSpec(
                client_type=client_spec.ClientType.ANTHROPIC,
                api_key_env="JUDGE_KEY",
            ),
        ),
    )

    resolved = run_experiment._resolve_paths(spec, tmp_path)

    assert resolved.repo_path == tmp_path / "kubernetes"
    assert resolved.instance_limit == 10
    assert resolved.agent_configs[0].context_files[0].source_path == tmp_path / "docs/source/api-conventions.md"
