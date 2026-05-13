"""Tests for AI agent runner and prompt composition."""

import datetime as dt
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import agent_runner
import atomic_constraint
import client_spec
import dataset_builder
import pr_collection
from pytest_mock import MockerFixture


def _write_existing_metadata(output_dir: Path, *, status: agent_runner.AgentRunStatus) -> None:
    metadata = {
        "status": status.value,
        "model": "agent-model",
        "context_strategy": agent_runner.ContextStrategy.NO_CONSTRAINTS.value,
        "pr_number": 42,
        "started_at": dt.datetime(2026, 5, 1, tzinfo=dt.UTC).isoformat(),
        "finished_at": dt.datetime(2026, 5, 1, tzinfo=dt.UTC).isoformat(),
        "duration_seconds": 0.0,
        "predicted_patch_bytes": 0,
        "attached_context_files": [],
        "exit_code": 0 if status == agent_runner.AgentRunStatus.COMPLETED else 1,
    }
    _ = (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )


def _make_successful_fake_run(
    repo_path: Path,
    results_root: Path,
) -> Callable[..., subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]]:
    worktree_dir = results_root / "docker-run" / "42" / "worktree"

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        _ = capture_output, check, text, timeout
        if command[:4] == ["git", "-C", str(repo_path), "archive"]:
            Path(command[-1]).write_text("archive", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["tar", "-xf"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["cp", "-cR"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "-C"] and command[3] in {"init", "config", "add", "commit"}:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["git", "-C", str(worktree_dir)]:
            return subprocess.CompletedProcess(command, 0, stdout=b"diff --git\n", stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout="agent done", stderr="")

    return fake_run


def _make_instance(root: Path) -> dataset_builder.DatasetInstance:
    detail = pr_collection.PullRequestDetail(
        pr_number=42,
        base_sha="def456",
        head_sha="abc123",
        title="Rename field",
        body="Body line.",
        labels=("kind/cleanup",),
        merged_at="2026-03-01T00:00:00Z",
        changed_files=("api/foo.go",),
        added_lines=3,
        deleted_lines=1,
    )
    (root / "base" / "api").mkdir(parents=True)
    _ = (root / "base" / "api" / "foo.go").write_text("package api\n", encoding="utf-8")
    return dataset_builder.DatasetInstance(detail=detail, root=root)


def _constraints() -> tuple[atomic_constraint.AtomicConstraint, ...]:
    return (
        atomic_constraint.AtomicConstraint(
            id="atom_001",
            normative_source_ids=("norm_014",),
            source_path=Path("docs/source/api-conventions.md"),
            source_span="219-219",
            title="Kind field",
            rule="All JSON objects include a kind field.",
            rationale="Consistency",
            judgeability=atomic_constraint.Judgeability.MACHINE_CHECKABLE,
        ),
    )


def test_agentic_workspace_prompt_includes_selected_rules_and_files_when_configured(tmp_path: Path) -> None:
    instance = _make_instance(tmp_path)
    docker_config = agent_runner.DockerAgentConfig(
        image="k8s-bench-agent",
        agent_command='agent run "$AGENT_PROMPT_PATH"',
    )
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.INLINE_CONSTRAINTS,
        docker=docker_config,
        initial_context_files=("api/foo.go",),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "Rename field" in prompt
    assert "Body line." in prompt
    assert "atom_001" in prompt
    assert "All JSON objects include a kind field." in prompt
    assert "### /work/api/foo.go" in prompt
    assert "package api" in prompt


def test_agentic_workspace_prompt_omits_constraints_when_strategy_is_no_constraints(tmp_path: Path) -> None:
    instance = _make_instance(tmp_path)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "/bench/task.json" in prompt
    assert "/bench/constraints.json" not in prompt
    assert "atom_001" not in prompt
    assert "All JSON objects include a kind field." not in prompt


def test_agentic_workspace_prompt_references_constraints_file_when_strategy_is_attached_file(
    tmp_path: Path,
) -> None:
    instance = _make_instance(tmp_path)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.ATTACHED_FILE_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "/bench/constraints.json" in prompt
    assert "All JSON objects include a kind field." not in prompt


def test_agentic_workspace_prompt_references_api_conventions_markdown_context_file(tmp_path: Path) -> None:
    instance = _make_instance(tmp_path)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.API_CONVENTIONS_MD,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        context_files=(
            agent_runner.AttachedContextFile(
                source_path=Path("docs/source/api-conventions.md"),
                bench_path="api-conventions.md",
                description="Kubernetes API conventions source document.",
            ),
        ),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "/bench/api-conventions.md" in prompt
    assert "Before editing, inspect `/bench/api-conventions.md`." in prompt
    assert "/bench/constraints.json" not in prompt


def test_agentic_workspace_prompt_references_normative_constraints_context_file(tmp_path: Path) -> None:
    instance = _make_instance(tmp_path)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NORMATIVE_CONSTRAINTS_223_JSON,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        context_files=(
            agent_runner.AttachedContextFile(
                source_path=Path("constraints/api_conventions_normative_constraints_223.json"),
                bench_path="api_conventions_normative_constraints.json",
                description="Reviewed normative constraints extracted from api-conventions.md.",
            ),
        ),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "/bench/api_conventions_normative_constraints.json" in prompt
    assert "223 reviewed normative constraints" in prompt
    assert "/bench/constraints.json" not in prompt


def test_agentic_workspace_prompt_references_atomic_constraints_context_file(tmp_path: Path) -> None:
    instance = _make_instance(tmp_path)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.ATOMIC_CONSTRAINTS_73_JSON,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        context_files=(
            agent_runner.AttachedContextFile(
                source_path=Path("constraints/api_conventions_atomic_constraints_73.json"),
                bench_path="api_conventions_atomic_constraints.json",
                description="Atomic constraints used by the evaluator.",
            ),
        ),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "/bench/api_conventions_atomic_constraints.json" in prompt
    assert "73 atomic Kubernetes API constraints" in prompt
    assert "/bench/constraints.json" not in prompt


def test_agentic_workspace_prompt_can_inline_selected_constraints(tmp_path: Path) -> None:
    instance = _make_instance(tmp_path)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.INLINE_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        initial_constraint_ids=("atom_001",),
    )

    prompt = agent_runner.build_agentic_workspace_prompt(instance, _constraints(), config)

    assert "atom_001" in prompt
    assert "All JSON objects include a kind field." in prompt
    assert "/bench/constraints.json" not in prompt


def test_run_docker_agentic_instance_runs_container_and_collects_git_diff(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        _ = capture_output, text, check, timeout
        if command[:4] == ["git", "-C", str(repo_path), "archive"]:
            archive_path = Path(command[-1])
            archive_path.write_text("archive", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["tar", "-xf"]:
            snapshot_dir = Path(command[-1])
            (snapshot_dir / "api").mkdir(parents=True, exist_ok=True)
            _ = (snapshot_dir / "api" / "foo.go").write_text("package api\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["cp", "-cR"]:
            worktree_path = Path(command[-1])
            (worktree_path / "api").mkdir(parents=True, exist_ok=True)
            _ = (worktree_path / "api" / "foo.go").write_text("package api\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "-C"] and command[3] in {"init", "config", "add", "commit"}:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["git", "-C", str(results_root / "docker-run" / "42" / "worktree")]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=b"diff --git a/api/foo.go b/api/foo.go\n+agentic\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(command, 0, stdout="agent done", stderr="")

    run_mock = mocker.patch("agent_runner.subprocess.run", autospec=True, side_effect=fake_run)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
            docker_args=("--network=none",),
        ),
    )

    result = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    output_dir = results_root / "docker-run" / "42"
    prompt = (output_dir / "prompt.txt").read_text(encoding="utf-8")
    assert result.predicted_patch.startswith("diff --git")
    assert "package api" not in prompt
    assert "All JSON objects include a kind field." not in prompt
    assert (output_dir / "bench_context" / "task.json").exists()
    assert not (output_dir / "bench_context" / "constraints.json").exists()
    assert "agent done" in (output_dir / "raw_response.txt").read_text(encoding="utf-8")
    assert (output_dir / "run_metadata.json").exists()
    assert not (output_dir / "worktree").exists()

    docker_command = next(
        call.args[0] for call in run_mock.call_args_list if call.args[0][:3] == ["docker", "run", "--rm"]
    )
    assert docker_command[:3] == ["docker", "run", "--rm"]
    assert "BASE_SHA=def456" in docker_command
    assert "OPENCODE_API_KEY" in docker_command
    assert f"{(output_dir / 'worktree').resolve()}:/work" in docker_command
    assert f"{(instance.root / 'base').resolve()}:/work" not in docker_command
    assert "--network=none" in docker_command
    assert "k8s-bench-agent" in docker_command
    diff_command = next(call.args[0] for call in run_mock.call_args_list if call.args[0][3] == "diff")
    assert diff_command == [
        "git",
        "-C",
        str(output_dir / "worktree"),
        "diff",
        "--no-color",
        "HEAD",
        "--",
        "api/foo.go",
    ]


def test_run_docker_agentic_instance_records_failures_without_raising(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, text, check, timeout
        if command[:4] == ["git", "-C", str(repo_path), "archive"]:
            Path(command[-1]).write_text("archive", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["tar", "-xf"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["cp", "-cR"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "-C"] and command[3] in {"init", "config", "add", "commit"}:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 42, stdout="agent stdout", stderr="agent stderr")

    _ = mocker.patch("agent_runner.subprocess.run", autospec=True, side_effect=fake_run)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
    )

    result = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    output_dir = results_root / "docker-run" / "42"
    assert result.status == agent_runner.AgentRunStatus.FAILED
    assert result.predicted_patch == ""
    assert "exit_code=42" in (output_dir / "raw_response.txt").read_text(encoding="utf-8")
    metadata = (output_dir / "run_metadata.json").read_text(encoding="utf-8")
    assert '"status": "failed"' in metadata
    assert (output_dir / "worktree").exists()


def test_run_docker_agentic_instance_records_opencode_error_with_zero_exit_as_failure(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, text, check, timeout
        if command[:4] == ["git", "-C", str(repo_path), "archive"]:
            Path(command[-1]).write_text("archive", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["tar", "-xf"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["cp", "-cR"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "-C"] and command[3] in {"init", "config", "add", "commit"}:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="Error: Bad Request: The input is longer than the model's context length.",
        )

    _ = mocker.patch("agent_runner.subprocess.run", autospec=True, side_effect=fake_run)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="Qwen/Qwen3.6-27B-FP8",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            backend=agent_runner.AgentBackend.OPENCODE,
            agent_command='opencode run --model "$MODEL" < "$AGENT_PROMPT_PATH"',
        ),
    )

    result = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    output_dir = results_root / "docker-run" / "42"
    assert result.status == agent_runner.AgentRunStatus.FAILED
    assert result.predicted_patch == ""
    raw_response = (output_dir / "raw_response.txt").read_text(encoding="utf-8")
    assert "exit_code=1" in raw_response
    assert "OpenCode reported an error despite exiting with code 0." in raw_response
    metadata = (output_dir / "run_metadata.json").read_text(encoding="utf-8")
    assert '"status": "failed"' in metadata
    assert '"exit_code": 1' in metadata


def test_run_docker_agentic_instance_skips_when_previous_run_metadata_marks_completed(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    output_dir = results_root / "docker-run" / "42"
    output_dir.mkdir(parents=True)
    _ = (output_dir / "predicted_patch.diff").write_text("diff --git\n", encoding="utf-8")
    _write_existing_metadata(output_dir, status=agent_runner.AgentRunStatus.COMPLETED)
    run_mock = mocker.patch("agent_runner.subprocess.run", autospec=True)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        skip_existing=True,
    )

    result = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=tmp_path / "repo",
    )

    assert result.status == agent_runner.AgentRunStatus.SKIPPED
    assert result.predicted_patch == "diff --git\n"
    assert '"status": "skipped"' in (output_dir / "run_metadata.json").read_text(encoding="utf-8")
    run_mock.assert_not_called()


def test_run_docker_agentic_instance_reruns_when_previous_run_metadata_marks_failed(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    output_dir = results_root / "docker-run" / "42"
    output_dir.mkdir(parents=True)
    _write_existing_metadata(output_dir, status=agent_runner.AgentRunStatus.FAILED)
    _ = (output_dir / "predicted_patch.diff").write_text("stale\n", encoding="utf-8")

    _ = mocker.patch(
        "agent_runner.subprocess.run", autospec=True, side_effect=_make_successful_fake_run(repo_path, results_root)
    )
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        skip_existing=True,
    )

    result = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    assert result.status == agent_runner.AgentRunStatus.COMPLETED
    assert result.predicted_patch.startswith("diff --git")
    assert '"status": "completed"' in (output_dir / "run_metadata.json").read_text(encoding="utf-8")


def test_run_docker_agentic_instance_injects_local_opencode_provider_config(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_mock = mocker.patch(
        "agent_runner.subprocess.run",
        autospec=True,
        side_effect=_make_successful_fake_run(repo_path, results_root),
    )
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8",
        max_tokens=8192,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            backend=agent_runner.AgentBackend.OPENCODE,
            agent_command='opencode run --model "$MODEL" < "$AGENT_PROMPT_PATH"',
            openai_compatible_provider=agent_runner.OpenAICompatibleProviderConfig(
                provider_id="sglang-local",
                name="SGLang local",
                client=client_spec.ClientSpec(
                    client_type=client_spec.ClientType.OPENAI_COMPATIBLE,
                    api_key_env="LOCAL_LLM_API_KEY",
                    base_url="http://localhost:8001/v1",
                ),
                context_limit=8192,
                output_limit=8192,
            ),
        ),
    )

    _ = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    docker_command = next(
        call.args[0] for call in run_mock.call_args_list if call.args[0][:3] == ["docker", "run", "--rm"]
    )
    assert "--add-host=host.docker.internal:host-gateway" in docker_command
    assert "LOCAL_LLM_API_KEY" in docker_command
    assert "MODEL=sglang-local/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8" in docker_command
    config_entry = next(item for item in docker_command if item.startswith("OPENCODE_CONFIG_CONTENT="))
    rendered = json.loads(config_entry.partition("=")[2])
    provider = rendered["provider"]["sglang-local"]
    assert provider["options"]["baseURL"] == "http://host.docker.internal:8001/v1"
    assert provider["options"]["apiKey"] == "{env:LOCAL_LLM_API_KEY}"
    assert provider["models"]["Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8"]["limit"] == {
        "context": 8192,
        "output": 8192,
    }


def test_run_docker_agentic_instance_keeps_localhost_for_host_network_opencode_provider(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_mock = mocker.patch(
        "agent_runner.subprocess.run",
        autospec=True,
        side_effect=_make_successful_fake_run(repo_path, results_root),
    )
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="Qwen/Qwen3.6-27B-FP8",
        max_tokens=8192,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            backend=agent_runner.AgentBackend.OPENCODE,
            agent_command='opencode run --model "$MODEL" < "$AGENT_PROMPT_PATH"',
            docker_args=("--network=host",),
            openai_compatible_provider=agent_runner.OpenAICompatibleProviderConfig(
                provider_id="sglang-local",
                name="SGLang local",
                client=client_spec.ClientSpec(
                    client_type=client_spec.ClientType.OPENAI_COMPATIBLE,
                    api_key_env="LOCAL_LLM_API_KEY",
                    base_url="http://localhost:8001/v1",
                ),
                context_limit=8192,
                output_limit=8192,
            ),
        ),
    )

    _ = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    docker_command = next(
        call.args[0] for call in run_mock.call_args_list if call.args[0][:3] == ["docker", "run", "--rm"]
    )
    assert "--network=host" in docker_command
    assert "--add-host=host.docker.internal:host-gateway" not in docker_command
    config_entry = next(item for item in docker_command if item.startswith("OPENCODE_CONFIG_CONTENT="))
    rendered = json.loads(config_entry.partition("=")[2])
    provider = rendered["provider"]["sglang-local"]
    assert provider["options"]["baseURL"] == "http://localhost:8001/v1"


def test_run_docker_agentic_instance_injects_mini_swe_agent_local_provider_env(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_mock = mocker.patch(
        "agent_runner.subprocess.run",
        autospec=True,
        side_effect=_make_successful_fake_run(repo_path, results_root),
    )
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="Qwen/Qwen3.6-27B-FP8",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent-mini-swe-agent",
            backend=agent_runner.AgentBackend.MINI_SWE_AGENT,
            agent_command='mini -y -m "$MODEL" -t "$(cat "$AGENT_PROMPT_PATH")"',
            docker_args=("--network=host",),
            openai_compatible_provider=agent_runner.OpenAICompatibleProviderConfig(
                provider_id="sglang-local",
                name="SGLang local",
                client=client_spec.ClientSpec(
                    client_type=client_spec.ClientType.OPENAI_COMPATIBLE,
                    api_key_env="LOCAL_LLM_API_KEY",
                    base_url="http://localhost:8002/v1",
                ),
                context_limit=16384,
                output_limit=4096,
            ),
        ),
    )

    _ = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    docker_command = next(
        call.args[0] for call in run_mock.call_args_list if call.args[0][:3] == ["docker", "run", "--rm"]
    )
    assert "--network=host" in docker_command
    assert "LOCAL_LLM_API_KEY" in docker_command
    assert "OPENAI_API_KEY" in docker_command
    assert "MODEL=openai/Qwen/Qwen3.6-27B-FP8" in docker_command
    assert "OPENAI_API_BASE=http://localhost:8002/v1" in docker_command
    assert "OPENAI_BASE_URL=http://localhost:8002/v1" in docker_command
    assert "MSWEA_COST_TRACKING=ignore_errors" in docker_command
    assert "k8s-bench-agent-mini-swe-agent" in docker_command


def test_run_docker_agentic_instance_records_docker_timeout_as_failure(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    results_root = tmp_path / "results"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = capture_output, check, text
        if command[:3] == ["docker", "run", "--rm"]:
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout or 0)
        if command[:4] == ["git", "-C", str(repo_path), "archive"]:
            Path(command[-1]).write_text("archive", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["tar", "-xf"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["cp", "-cR"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "-C"] and command[3] in {"init", "config", "add", "commit"}:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    _ = mocker.patch("agent_runner.subprocess.run", autospec=True, side_effect=fake_run)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
            agent_timeout_seconds=30,
        ),
    )

    result = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )

    output_dir = results_root / "docker-run" / "42"
    assert result.status == agent_runner.AgentRunStatus.FAILED
    assert result.predicted_patch == ""
    raw_response = (output_dir / "raw_response.txt").read_text(encoding="utf-8")
    assert "agent timed out after 30s" in raw_response
    assert "exit_code=124" in raw_response
    assert '"status": "failed"' in (output_dir / "run_metadata.json").read_text(encoding="utf-8")


def test_run_docker_agentic_instance_copies_attached_context_files(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    context_source = tmp_path / "api-conventions.md"
    _ = context_source.write_text("# API conventions\n", encoding="utf-8")

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        _ = capture_output, text, check, timeout
        if command[:4] == ["git", "-C", str(repo_path), "archive"]:
            Path(command[-1]).write_text("archive", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["tar", "-xf"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["cp", "-cR"]:
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "-C"] and command[3] in {"init", "config", "add", "commit"}:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["git", "-C", str(tmp_path / "results" / "docker-run" / "42" / "worktree")]:
            return subprocess.CompletedProcess(command, 0, stdout=b"diff --git\n", stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout="agent done", stderr="")

    _ = mocker.patch("agent_runner.subprocess.run", autospec=True, side_effect=fake_run)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.API_CONVENTIONS_MD,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        context_files=(
            agent_runner.AttachedContextFile(
                source_path=context_source,
                bench_path="api-conventions.md",
                description="Kubernetes API conventions source document.",
            ),
        ),
    )

    _ = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=tmp_path / "results",
        repo_path=repo_path,
    )

    copied = tmp_path / "results" / "docker-run" / "42" / "bench_context" / "api-conventions.md"
    assert copied.read_text(encoding="utf-8") == "# API conventions\n"


def test_git_worktree_strategy_mounts_real_git_worktree(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance_root = tmp_path / "datasets" / "abc123"
    instance_root.mkdir(parents=True)
    instance = _make_instance(instance_root)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        _ = capture_output, text, check, timeout
        if command[:2] == ["git", "-C"] and "worktree" in command:
            if "add" in command:
                Path(command[-2]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["git", "-C", str(tmp_path / "results" / "docker-run" / "42" / "worktree")]:
            return subprocess.CompletedProcess(command, 0, stdout=b"diff --git\n", stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout="agent done", stderr="")

    run_mock = mocker.patch("agent_runner.subprocess.run", autospec=True, side_effect=fake_run)
    config = agent_runner.AgentRunConfig(
        run_id="docker-run",
        model="agent-model",
        max_tokens=4096,
        context_strategy=agent_runner.ContextStrategy.NO_CONSTRAINTS,
        docker=agent_runner.DockerAgentConfig(
            image="k8s-bench-agent",
            agent_command='agent run "$AGENT_PROMPT_PATH"',
        ),
        worktree_strategy=agent_runner.WorktreeStrategy.GIT_WORKTREE,
    )

    _ = agent_runner.run_agent_on_instance(
        instance=instance,
        constraints=_constraints(),
        config=config,
        results_root=tmp_path / "results",
        repo_path=repo_path,
    )

    commands = [call.args[0] for call in run_mock.call_args_list]
    assert [
        "git",
        "-C",
        str(repo_path),
        "worktree",
        "add",
        "--detach",
        str(tmp_path / "results" / "docker-run" / "42" / "worktree"),
        "def456",
    ] in commands
    assert not any(command[:4] == ["git", "-C", str(repo_path), "archive"] for command in commands)
