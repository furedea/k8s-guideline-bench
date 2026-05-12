"""Tests for the experiment orchestration layer."""

import json
from pathlib import Path

import agent_runner
import claude_cli_client
import client_spec
import completion_client
import dataset_builder
import experiment
import judge
import pr_collection
import pytest
from pytest_mock import MockerFixture


def _materialize_instance(datasets_root: Path, pr_number: int) -> dataset_builder.DatasetInstance:
    detail = pr_collection.PullRequestDetail(
        pr_number=pr_number,
        base_sha=f"base-{pr_number}",
        head_sha=f"head-{pr_number}",
        title="Refactor",
        body="",
        labels=("kind/cleanup",),
        merged_at="2026-03-01T00:00:00Z",
        changed_files=("api/foo.go",),
        added_lines=1,
        deleted_lines=0,
    )
    instance_root = datasets_root / str(pr_number)
    (instance_root / "base" / "api").mkdir(parents=True)
    _ = (instance_root / "base" / "api" / "foo.go").write_text("package api\n", encoding="utf-8")
    _ = (instance_root / "gold_patch.diff").write_text("diff --git a/api/foo.go b/api/foo.go\n", encoding="utf-8")
    return dataset_builder.DatasetInstance(detail=detail, root=instance_root)


def _write_constraints_file(path: Path) -> None:
    constraints = {
        "constraints": [
            {
                "id": "atom_001",
                "normative_source_ids": ["norm_014"],
                "source_path": "docs/source/api-conventions.md",
                "source_span": "219-219",
                "title": "Kind field",
                "rule": "All JSON objects include a kind field.",
                "rationale": "Consistency",
                "judgeability": "machine_checkable",
            },
        ],
    }
    _ = path.write_text(json.dumps(constraints), encoding="utf-8")


class _StubJudgeClient:
    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        _ = system, user, model, max_tokens
        return '{"verdict": "compliant", "confidence": 0.9, "rationale": ""}'


def _stub_factory(spec: client_spec.ClientSpec) -> completion_client.CompletionClient:
    assert spec.api_key_env == "JUDGE_KEY"
    return _StubJudgeClient()


def _make_experiment_spec(tmp_path: Path) -> experiment.ExperimentSpec:
    datasets_root = tmp_path / "datasets"
    datasets_root.mkdir()
    results_root = tmp_path / "results"
    constraints_file = tmp_path / "constraints.json"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _write_constraints_file(constraints_file)
    agent_cfg = agent_runner.AgentRunConfig(
        run_id="run-001",
        model="m-a",
        max_tokens=1024,
        context_strategy=agent_runner.ContextStrategy.INLINE_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
    )
    judge_cfg = judge.JudgeConfig(
        model="m-j",
        max_tokens=256,
        system_prompt="judge",
        client=client_spec.ClientSpec(
            client_type=client_spec.ClientType.ANTHROPIC,
            api_key_env="JUDGE_KEY",
        ),
    )
    return experiment.ExperimentSpec(
        datasets_root=datasets_root,
        results_root=results_root,
        repo_path=repo_path,
        constraints_file=constraints_file,
        agent_configs=(agent_cfg,),
        judge_config=judge_cfg,
    )


def test_run_experiment_executes_agent_and_judge_for_each_instance(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    spec = _make_experiment_spec(tmp_path)
    instances = (_materialize_instance(spec.datasets_root, 42),)
    _ = mocker.patch(
        "agent_runner.run_agent_on_instances",
        autospec=True,
        return_value=(agent_runner.AgentRunResult(run_id="run-001", predicted_patch="diff\n"),),
    )

    report = experiment.run_experiment(spec, instances, client_factory=_stub_factory)

    assert len(report.runs) == 1
    run = report.runs[0]
    assert run.run_id == "run-001"
    assert run.instance_ids == ("42",)
    assert run.summary.total == 1
    assert run.summary.compliant == 1
    assert (spec.results_root / "run-001" / "42" / "judgments.json").exists()
    assert (spec.results_root / "experiment_report.json").exists()


def test_run_experiment_builds_only_judge_client_for_agent_runs(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    spec = _make_experiment_spec(tmp_path)
    instances = (_materialize_instance(spec.datasets_root, 42),)
    _ = mocker.patch(
        "agent_runner.run_agent_on_instances",
        autospec=True,
        return_value=(agent_runner.AgentRunResult(run_id="run-001", predicted_patch="diff\n"),),
    )
    call_count = 0

    def counting_factory(c_spec: client_spec.ClientSpec) -> completion_client.CompletionClient:
        nonlocal call_count
        assert c_spec.api_key_env == "JUDGE_KEY"
        call_count += 1
        return _StubJudgeClient()

    _ = experiment.run_experiment(spec, instances, client_factory=counting_factory)

    assert call_count == 1


def test_run_experiment_counts_instances_with_verification_failures(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    spec = _make_experiment_spec(tmp_path)
    instances = (
        _materialize_instance(spec.datasets_root, 42),
        _materialize_instance(spec.datasets_root, 43),
    )
    _ = mocker.patch(
        "agent_runner.run_agent_on_instances",
        autospec=True,
        return_value=(
            agent_runner.AgentRunResult(run_id="run-001", predicted_patch="diff-a\n"),
            agent_runner.AgentRunResult(run_id="run-001", predicted_patch="diff-b\n"),
        ),
    )

    def fake_judge_instance(
        *,
        instance: dataset_builder.DatasetInstance,
        run_id: str,
        **_: object,
    ) -> judge.InstanceJudgment:
        instance_id = str(instance.detail.pr_number)
        if instance_id == "42":
            return judge.InstanceJudgment(
                instance_id=instance_id,
                run_id=run_id,
                judgments=(
                    judge.ConstraintJudgment(
                        constraint_id="c1",
                        verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                        confidence=0.0,
                        rationale="",
                        status=judge.JudgmentStatus.PATCH_APPLY_FAILURE,
                    ),
                ),
            )
        return judge.InstanceJudgment(
            instance_id=instance_id,
            run_id=run_id,
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="",
                ),
            ),
        )

    _ = mocker.patch("judge.judge_instance", side_effect=fake_judge_instance)

    report = experiment.run_experiment(spec, instances, client_factory=_stub_factory)

    run = report.runs[0]
    assert run.instances_with_patch_apply_failure == 1
    assert run.instances_with_build_failure == 0
    assert run.instances_with_test_failure == 0
    assert run.instances_judged == 1


def test_run_experiment_skips_judge_for_failed_agent_results(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    spec = _make_experiment_spec(tmp_path)
    instances = (
        _materialize_instance(spec.datasets_root, 42),
        _materialize_instance(spec.datasets_root, 43),
    )
    _ = mocker.patch(
        "agent_runner.run_agent_on_instances",
        autospec=True,
        return_value=(
            agent_runner.AgentRunResult(run_id="run-001", predicted_patch="diff\n"),
            agent_runner.AgentRunResult(
                run_id="run-001",
                predicted_patch="",
                status=agent_runner.AgentRunStatus.FAILED,
            ),
        ),
    )

    report = experiment.run_experiment(spec, instances, client_factory=_stub_factory)

    run = report.runs[0]
    assert run.instance_ids == ("42", "43")
    assert run.agent_completed == 1
    assert run.agent_failed == 1
    assert run.agent_skipped == 0
    assert run.summary.total == 1
    assert (spec.results_root / "run-001" / "42" / "judgments.json").exists()
    assert not (spec.results_root / "run-001" / "43" / "judgments.json").exists()


def test_run_experiment_propagates_claude_cli_fatal_error_from_judge(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    spec = _make_experiment_spec(tmp_path)
    instances = (_materialize_instance(spec.datasets_root, 42),)
    _ = mocker.patch(
        "agent_runner.run_agent_on_instances",
        autospec=True,
        return_value=(agent_runner.AgentRunResult(run_id="run-001", predicted_patch="diff\n"),),
    )
    fatal = claude_cli_client.ClaudeCliFatalError(returncode=2, stdout="", stderr="auth required")
    _ = mocker.patch("judge.judge_instance", side_effect=fatal)

    with pytest.raises(claude_cli_client.ClaudeCliFatalError) as exc_info:
        _ = experiment.run_experiment(spec, instances, client_factory=_stub_factory)

    assert exc_info.value.returncode == 2
    assert not (spec.results_root / "experiment_report.json").exists()


def test_load_experiment_spec_parses_json(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.json"
    _ = spec_path.write_text(
        json.dumps(
            {
                "datasets_root": "datasets",
                "results_root": "results",
                "repo_path": "kubernetes",
                "constraints_file": "constraints.json",
                "instance_limit": 10,
                "agent_configs": [
                    {
                        "run_id": "run-001",
                        "model": "m",
                        "max_tokens": 1024,
                        "context_strategy": "inline_constraints",
                        "docker": {
                            "image": "k8s-bench-agent",
                            "agent_command": 'agent run "$AGENT_PROMPT_PATH"',
                        },
                    },
                ],
                "judge_config": {
                    "model": "m",
                    "max_tokens": 256,
                    "system_prompt": "judge",
                    "client": {
                        "client_type": "anthropic",
                        "api_key_env": "JUDGE_KEY",
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    loaded = experiment.load_experiment_spec(spec_path)

    assert loaded.datasets_root == Path("datasets")
    assert loaded.repo_path == Path("kubernetes")
    assert loaded.instance_limit == 10
    assert loaded.agent_configs[0].run_id == "run-001"


def test_load_experiment_spec_parses_attached_context_files(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.json"
    _ = spec_path.write_text(
        json.dumps(
            {
                "datasets_root": "datasets",
                "results_root": "results",
                "repo_path": "kubernetes",
                "constraints_file": "constraints.json",
                "agent_configs": [
                    {
                        "run_id": "pilot-api-doc",
                        "model": "opencode-go/deepseek-v4-flash",
                        "max_tokens": 8192,
                        "context_strategy": "api_conventions_md",
                        "worktree_strategy": "cow_snapshot",
                        "docker": {
                            "image": "k8s-bench-agent",
                            "agent_command": 'opencode run --model "$MODEL" < "$AGENT_PROMPT_PATH"',
                        },
                        "context_files": [
                            {
                                "source_path": "docs/source/api-conventions.md",
                                "bench_path": "api-conventions.md",
                                "description": "Kubernetes API conventions source document.",
                            },
                        ],
                    },
                ],
                "judge_config": {
                    "model": "m",
                    "max_tokens": 256,
                    "system_prompt": "judge",
                    "client": {
                        "client_type": "anthropic",
                        "api_key_env": "JUDGE_KEY",
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    loaded = experiment.load_experiment_spec(spec_path)

    config = loaded.agent_configs[0]
    assert config.context_strategy == agent_runner.ContextStrategy.API_CONVENTIONS_MD
    assert config.worktree_strategy == agent_runner.WorktreeStrategy.COW_SNAPSHOT
    assert config.context_files[0].source_path == Path("docs/source/api-conventions.md")
    assert config.context_files[0].bench_path == "api-conventions.md"


def test_load_experiment_spec_expands_agent_matrix(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.json"
    _ = spec_path.write_text(
        json.dumps(
            {
                "datasets_root": "datasets",
                "results_root": "results/pilot",
                "repo_path": "kubernetes",
                "constraints_file": "constraints/api_conventions_atomic_constraints_73.json",
                "agent_matrix": {
                    "run_id_prefix": "pilot",
                    "models": [
                        "opencode-go/qwen3.6-plus",
                        "opencode-go/minimax-m2.7",
                    ],
                    "context_strategies": [
                        "no_constraints",
                        "api_conventions_md",
                        "atomic_constraints_73_json",
                    ],
                    "max_tokens": 8192,
                    "docker": {
                        "image": "k8s-bench-agent",
                        "agent_command": 'opencode run --model "$MODEL" < "$AGENT_PROMPT_PATH"',
                    },
                    "skip_existing": True,
                },
                "judge_config": {
                    "model": "sonnet",
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

    loaded = experiment.load_experiment_spec(spec_path)

    assert tuple(config.run_id for config in loaded.agent_configs) == (
        "pilot_qwen3_6_plus_no_constraints",
        "pilot_qwen3_6_plus_api_conventions_md",
        "pilot_qwen3_6_plus_atomic_constraints_73_json",
        "pilot_minimax_m2_7_no_constraints",
        "pilot_minimax_m2_7_api_conventions_md",
        "pilot_minimax_m2_7_atomic_constraints_73_json",
    )
    assert loaded.judge_config.skip_existing is True
    api_doc = loaded.agent_configs[1]
    assert api_doc.context_files[0].source_path == Path("docs/source/api-conventions.md")
    assert api_doc.context_files[0].bench_path == "api-conventions.md"
    atomic = loaded.agent_configs[2]
    assert atomic.context_files[0].source_path == Path("constraints/api_conventions_atomic_constraints_73.json")
    assert atomic.context_files[0].bench_path == "api_conventions_atomic_constraints.json"
