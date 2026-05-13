"""AI Coding Agent runner that drives refactoring on dataset instances."""

import datetime as dt
import enum
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Self, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

import atomic_constraint
import base
import client_spec
import dataset_builder
import pr_body
import pydantic
import tqdm

logger = logging.getLogger(__name__)


class ContextStrategy(enum.StrEnum):
    """How atomic constraints are delivered to the agent."""

    INLINE_CONSTRAINTS = "inline_constraints"
    ATTACHED_FILE_CONSTRAINTS = "attached_file_constraints"
    API_CONVENTIONS_MD = "api_conventions_md"
    ATOMIC_CONSTRAINTS_73_JSON = "atomic_constraints_73_json"
    NORMATIVE_CONSTRAINTS_223_JSON = "normative_constraints_223_json"
    NO_CONSTRAINTS = "no_constraints"


class AgentRunStatus(enum.StrEnum):
    """Execution status for one agent run on one dataset instance."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorktreeStrategy(enum.StrEnum):
    """How the editable agent worktree is prepared."""

    COW_SNAPSHOT = "cow_snapshot"
    GIT_WORKTREE = "git_worktree"


class AgentBackend(enum.StrEnum):
    """How the Docker command is adapted for an agent runtime."""

    CUSTOM_CLI = "custom_cli"
    OPENCODE = "opencode"
    MINI_SWE_AGENT = "mini_swe_agent"


class DockerAgentConfig(base.FrozenModel):
    """Docker-backed agentic execution configuration."""

    image: str
    backend: AgentBackend = AgentBackend.CUSTOM_CLI
    agent_command: str
    docker_args: tuple[str, ...] = ()
    env_passthrough: tuple[str, ...] = ("OPENCODE_API_KEY",)
    openai_compatible_provider: OpenAICompatibleProviderConfig | None = None
    worktree_path: str = "/work"
    bench_context_path: str = "/bench"
    output_path: str = "/out"
    agent_timeout_seconds: int = 1800

    @pydantic.field_validator("docker_args", "env_passthrough", mode="before")
    @classmethod
    def validate_string_tuple(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[str]", value))
        return value

    @pydantic.field_validator("backend", mode="before")
    @classmethod
    def validate_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return AgentBackend(value)
        return value

    @pydantic.model_validator(mode="after")
    def validate_backend_config(self) -> Self:
        provider_backends = {AgentBackend.OPENCODE, AgentBackend.MINI_SWE_AGENT}
        if self.openai_compatible_provider is not None and self.backend not in provider_backends:
            msg = "`openai_compatible_provider` requires `backend` to be `opencode` or `mini_swe_agent`."
            raise ValueError(msg)
        return self


class OpenAICompatibleProviderConfig(base.FrozenModel):
    """Custom OpenCode provider backed by an OpenAI-compatible endpoint."""

    provider_id: str
    name: str
    client: client_spec.ClientSpec
    context_limit: int
    output_limit: int

    @pydantic.model_validator(mode="after")
    def validate_client(self) -> Self:
        if self.client.client_type != client_spec.ClientType.OPENAI_COMPATIBLE:
            msg = "`openai_compatible_provider.client.client_type` must be `openai_compatible`."
            raise ValueError(msg)
        if self.client.base_url is None:
            msg = "`openai_compatible_provider.client.base_url` is required."
            raise ValueError(msg)
        if self.client.api_key_env is None:
            msg = "`openai_compatible_provider.client.api_key_env` is required."
            raise ValueError(msg)
        return self


class AttachedContextFile(base.FrozenModel):
    """A host file copied into the Docker bench context."""

    source_path: Path
    bench_path: str
    description: str

    @pydantic.field_validator("source_path", mode="before")
    @classmethod
    def validate_source_path(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value)
        return value


class AgentRunConfig(base.FrozenModel):
    """Configuration for a single Docker-backed agentic experiment run."""

    run_id: str
    model: str
    max_tokens: int
    context_strategy: ContextStrategy
    docker: DockerAgentConfig
    initial_context_files: tuple[str, ...] = ()
    initial_constraint_ids: tuple[str, ...] = ()
    context_files: tuple[AttachedContextFile, ...] = ()
    skip_existing: bool = False
    keep_worktree: bool = False
    keep_failed_worktree: bool = True
    worktree_strategy: WorktreeStrategy = WorktreeStrategy.COW_SNAPSHOT

    @pydantic.field_validator("context_strategy", mode="before")
    @classmethod
    def validate_context_strategy(cls, value: object) -> object:
        if isinstance(value, str):
            return ContextStrategy(value)
        return value

    @pydantic.field_validator("worktree_strategy", mode="before")
    @classmethod
    def validate_worktree_strategy(cls, value: object) -> object:
        if isinstance(value, str):
            return WorktreeStrategy(value)
        return value

    @pydantic.field_validator("initial_context_files", "initial_constraint_ids", mode="before")
    @classmethod
    def validate_string_tuple(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[str]", value))
        return value

    @pydantic.field_validator("context_files", mode="before")
    @classmethod
    def validate_context_files(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[AttachedContextFile]", value))
        return value


class AgentRunResult(base.FrozenModel):
    """Result artifact produced by running the agent on a dataset instance.

    The verbose per-run artifacts (prompt, raw response, patch) are persisted
    under `results_root/<run_id>/<sha>/`; only fields downstream consumers
    actually read are returned.
    """

    run_id: str
    predicted_patch: str
    status: AgentRunStatus = AgentRunStatus.COMPLETED


class AgentRunMetadata(base.FrozenModel):
    """Small machine-readable execution record for one agent run."""

    status: AgentRunStatus
    model: str
    context_strategy: ContextStrategy
    pr_number: int
    started_at: str
    finished_at: str
    duration_seconds: float
    predicted_patch_bytes: int
    attached_context_files: tuple[str, ...]
    exit_code: int | None = None


class BackendInvocation(base.FrozenModel):
    """Docker command fragments derived from the selected agent backend."""

    model: str
    env_passthrough: tuple[str, ...]
    env_args: tuple[str, ...]
    docker_args: tuple[str, ...]


DOCKER_PROMPT_FILENAME = "prompt.txt"
DOCKER_TASK_FILENAME = "task.json"
DOCKER_CONSTRAINTS_FILENAME = "constraints.json"
RUN_METADATA_FILENAME = "run_metadata.json"
AGENT_TIMEOUT_EXIT_CODE = 124
AGENT_REPORTED_ERROR_EXIT_CODE = 1
OPENCODE_CONFIG_ENV = "OPENCODE_CONFIG_CONTENT"
OPENCODE_CONFIG_SCHEMA = "https://opencode.ai/config.json"
OPENAI_COMPATIBLE_PACKAGE = "@ai-sdk/openai-compatible"
HOST_INTERNAL_NAME = "host.docker.internal"
HOST_INTERNAL_DOCKER_ARG = f"--add-host={HOST_INTERNAL_NAME}:host-gateway"
HOST_NETWORK_DOCKER_ARG = "--network=host"
LOCALHOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def build_agentic_workspace_prompt(
    instance: dataset_builder.DatasetInstance,
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    config: AgentRunConfig,
) -> str:
    """Build the initial prompt for a Docker-backed agentic run."""
    docker_config = config.docker
    task_path = f"{docker_config.bench_context_path}/{DOCKER_TASK_FILENAME}"
    constraints_path = f"{docker_config.bench_context_path}/{DOCKER_CONSTRAINTS_FILENAME}"
    sections: list[str] = [
        "## Task",
        instance.detail.title,
    ]
    cleaned_body = pr_body.clean_pr_body(instance.detail.body)
    if cleaned_body:
        sections.append("")
        sections.append(cleaned_body)
    sections.extend(
        [
            "",
            "## Workspace",
            f"- Repository root: `{docker_config.worktree_path}`",
            f"- Task metadata: `{task_path}`",
        ],
    )
    if config.context_strategy == ContextStrategy.ATTACHED_FILE_CONSTRAINTS:
        sections.append(f"- Project guidelines: `{constraints_path}`")
    sections.extend(_render_attached_context_file_references(config))
    sections.extend(
        [
            "",
            "Inspect the repository and the referenced metadata files yourself.",
            "Modify files in the repository worktree to complete the refactoring.",
            "Preserve behavior and leave the worktree with only the intended changes.",
        ],
    )
    sections.extend(_render_inline_constraints(constraints, config))
    sections.extend(_render_initial_file_context(instance, docker_config, config))
    return "\n".join(sections).strip() + "\n"


def run_agent_on_instance(
    instance: dataset_builder.DatasetInstance,
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    config: AgentRunConfig,
    results_root: Path,
    repo_path: Path,
) -> AgentRunResult:
    """Run the Docker-backed agent on a single dataset instance and persist artifacts."""
    return _run_docker_agent_on_instance(
        instance=instance,
        constraints=constraints,
        config=config,
        results_root=results_root,
        repo_path=repo_path,
    )


def run_agent_on_instances(
    instances: tuple[dataset_builder.DatasetInstance, ...],
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    config: AgentRunConfig,
    results_root: Path,
    repo_path: Path,
) -> tuple[AgentRunResult, ...]:
    """Run the Docker-backed agent over multiple dataset instances."""
    progress = tqdm.tqdm(instances, desc=f"agent[{config.run_id}]", unit="pr", ncols=88)
    return tuple(
        run_agent_on_instance(instance, constraints, config, results_root, repo_path=repo_path)
        for instance in progress
    )


def _render_inline_constraints(
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    config: AgentRunConfig,
) -> list[str]:
    if config.context_strategy != ContextStrategy.INLINE_CONSTRAINTS or not constraints:
        return []
    selected_constraints = _select_constraints(constraints, config.initial_constraint_ids)
    lines = ["## Project guidelines"]
    lines.extend(
        f"- **{constraint.id}** ({constraint.title}): {constraint.rule}" for constraint in selected_constraints
    )
    lines.append("")
    return lines


def _render_attached_context_file_references(config: AgentRunConfig) -> list[str]:
    if not config.context_files:
        return []
    lines = ["- Attached context files:"]
    lines.extend(
        f"  - `{config.docker.bench_context_path}/{context_file.bench_path}`: {context_file.description}"
        for context_file in config.context_files
    )
    if config.context_strategy == ContextStrategy.API_CONVENTIONS_MD:
        lines.extend(
            [
                "- Before editing, inspect `/bench/api-conventions.md`.",
                "- Use it as the Kubernetes API convention rulebook.",
                "- Search for sections relevant to the changed files and task.",
                "- Do not apply unrelated guidance mechanically.",
            ],
        )
    if config.context_strategy == ContextStrategy.NORMATIVE_CONSTRAINTS_223_JSON:
        lines.extend(
            [
                "- Before editing, inspect `/bench/api_conventions_normative_constraints.json`.",
                "- It contains 223 reviewed normative constraints extracted from `docs/source/api-conventions.md`.",
                "- Identify constraints relevant to the changed files and task.",
                "- Do not apply unrelated constraints mechanically.",
            ],
        )
    if config.context_strategy == ContextStrategy.ATOMIC_CONSTRAINTS_73_JSON:
        lines.extend(
            [
                "- Before editing, inspect `/bench/api_conventions_atomic_constraints.json`.",
                "- It contains the 73 atomic Kubernetes API constraints used by the evaluator.",
                "- Identify constraints relevant to the changed files and task.",
                "- Do not apply unrelated constraints mechanically.",
            ],
        )
    return lines


def _render_initial_file_context(
    instance: dataset_builder.DatasetInstance,
    docker_config: DockerAgentConfig,
    config: AgentRunConfig,
) -> list[str]:
    if not config.initial_context_files:
        return []
    sections: list[str] = []
    base_dir = instance.root / "base"
    sections.extend(["## Initial file context", ""])
    for relative_path in config.initial_context_files:
        file_path = base_dir / relative_path
        if not file_path.exists():
            continue
        sections.append(f"### {docker_config.worktree_path}/{relative_path}")
        sections.append("```go")
        sections.append(file_path.read_text(encoding="utf-8").rstrip("\n"))
        sections.append("```")
        sections.append("")
    return sections


def _run_docker_agent_on_instance(
    instance: dataset_builder.DatasetInstance,
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    config: AgentRunConfig,
    results_root: Path,
    repo_path: Path,
) -> AgentRunResult:
    docker_config = config.docker
    output_dir = results_root / config.run_id / str(instance.detail.pr_number)
    base_snapshot_dir = results_root / "base_snapshots" / str(instance.detail.pr_number)
    context_dir = output_dir / "bench_context"
    worktree_dir = output_dir / "worktree"
    predicted_patch_path = output_dir / "predicted_patch.diff"
    metadata_path = output_dir / RUN_METADATA_FILENAME
    if config.skip_existing and _is_previous_run_skippable(metadata_path):
        started_at = dt.datetime.now(tz=dt.UTC)
        _write_run_metadata(
            output_dir=output_dir,
            instance=instance,
            config=config,
            status=AgentRunStatus.SKIPPED,
            started_at=started_at,
            predicted_patch_path=predicted_patch_path,
            exit_code=None,
        )
        return AgentRunResult(
            run_id=config.run_id,
            predicted_patch=_read_predicted_patch(predicted_patch_path),
            status=AgentRunStatus.SKIPPED,
        )

    started_at = dt.datetime.now(tz=dt.UTC)
    output_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)
    _prepare_agent_worktree(
        repo_path=repo_path,
        base_snapshot_dir=base_snapshot_dir,
        worktree_dir=worktree_dir,
        base_sha=instance.detail.base_sha,
        strategy=config.worktree_strategy,
    )

    prompt = build_agentic_workspace_prompt(instance, constraints, config)
    _ = (output_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    _ = (context_dir / DOCKER_PROMPT_FILENAME).write_text(prompt, encoding="utf-8")
    _write_docker_context(context_dir, instance, constraints, config)

    completed = _run_docker_agent_command(
        instance=instance,
        config=config,
        docker_config=docker_config,
        output_dir=output_dir,
        context_dir=context_dir,
        worktree_dir=worktree_dir,
    )
    completed = _normalize_agent_completed_process(completed, config)
    raw_response = _render_docker_raw_response(completed)
    _ = (output_dir / "raw_response.txt").write_text(raw_response, encoding="utf-8")
    if completed.returncode != 0:
        _write_run_metadata(
            output_dir=output_dir,
            instance=instance,
            config=config,
            status=AgentRunStatus.FAILED,
            started_at=started_at,
            predicted_patch_path=predicted_patch_path,
            exit_code=completed.returncode,
        )
        if not config.keep_failed_worktree:
            shutil.rmtree(worktree_dir, ignore_errors=True)
        logger.warning(
            {
                "action": "agent_run_failed",
                "run_id": config.run_id,
                "pr_number": instance.detail.pr_number,
                "exit_code": completed.returncode,
            }
        )
        return AgentRunResult(
            run_id=config.run_id,
            predicted_patch="",
            status=AgentRunStatus.FAILED,
        )

    _collect_predicted_patch(worktree_dir, instance.detail.changed_files, predicted_patch_path)
    predicted_patch = predicted_patch_path.read_text(encoding="utf-8") if predicted_patch_path.exists() else ""
    _write_run_metadata(
        output_dir=output_dir,
        instance=instance,
        config=config,
        status=AgentRunStatus.COMPLETED,
        started_at=started_at,
        predicted_patch_path=predicted_patch_path,
        exit_code=completed.returncode,
    )
    if not config.keep_worktree:
        shutil.rmtree(worktree_dir, ignore_errors=True)
    return AgentRunResult(run_id=config.run_id, predicted_patch=predicted_patch)


def _write_docker_context(
    context_dir: Path,
    instance: dataset_builder.DatasetInstance,
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    config: AgentRunConfig,
) -> None:
    _ = (context_dir / DOCKER_TASK_FILENAME).write_text(
        json.dumps(instance.detail.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if config.context_strategy != ContextStrategy.ATTACHED_FILE_CONSTRAINTS:
        _copy_attached_context_files(context_dir, config.context_files)
        return
    selected_constraints = _select_constraints(constraints, config.initial_constraint_ids)
    _ = (context_dir / DOCKER_CONSTRAINTS_FILENAME).write_text(
        json.dumps(
            {"constraints": [constraint.model_dump(mode="json") for constraint in selected_constraints]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _copy_attached_context_files(context_dir, config.context_files)


def _copy_attached_context_files(
    context_dir: Path,
    context_files: tuple[AttachedContextFile, ...],
) -> None:
    for context_file in context_files:
        destination = context_dir / context_file.bench_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(context_file.source_path, destination)


def _select_constraints(
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    selected_ids: tuple[str, ...],
) -> tuple[atomic_constraint.AtomicConstraint, ...]:
    if not selected_ids:
        return constraints
    selected_id_set = set(selected_ids)
    return tuple(constraint for constraint in constraints if constraint.id in selected_id_set)


def _run_docker_agent_command(
    instance: dataset_builder.DatasetInstance,
    config: AgentRunConfig,
    docker_config: DockerAgentConfig,
    output_dir: Path,
    context_dir: Path,
    worktree_dir: Path,
) -> subprocess.CompletedProcess[str]:
    prompt_path = f"{docker_config.bench_context_path}/{DOCKER_PROMPT_FILENAME}"
    task_path = f"{docker_config.bench_context_path}/{DOCKER_TASK_FILENAME}"
    constraints_path = f"{docker_config.bench_context_path}/{DOCKER_CONSTRAINTS_FILENAME}"
    shell_script = f"set -euxCo pipefail\n{docker_config.agent_command}"
    backend_invocation = _build_backend_invocation(config.model, docker_config)
    command = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"BASE_SHA={instance.detail.base_sha}",
        "-e",
        f"AGENT_PROMPT_PATH={prompt_path}",
        "-e",
        f"TASK_PATH={task_path}",
        "-e",
        f"CONSTRAINTS_PATH={constraints_path}",
        "-e",
        f"MODEL={backend_invocation.model}",
        "-e",
        f"MAX_TOKENS={config.max_tokens}",
        *_render_env_passthrough_args(backend_invocation.env_passthrough),
        *backend_invocation.env_args,
        "-v",
        f"{worktree_dir.resolve()}:{docker_config.worktree_path}",
        "-v",
        f"{context_dir.resolve()}:{docker_config.bench_context_path}:ro",
        "-v",
        f"{output_dir.resolve()}:{docker_config.output_path}",
        *backend_invocation.docker_args,
        docker_config.image,
        "bash",
        "-lc",
        shell_script,
    ]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=docker_config.agent_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _completed_process_from_timeout(command, docker_config.agent_timeout_seconds)


def _render_env_passthrough_args(env_names: tuple[str, ...]) -> list[str]:
    args: list[str] = []
    for env_name in env_names:
        args.extend(("-e", env_name))
    return args


def _build_backend_invocation(model: str, docker_config: DockerAgentConfig) -> BackendInvocation:
    if docker_config.backend == AgentBackend.OPENCODE:
        return _build_opencode_invocation(model, docker_config)
    if docker_config.backend == AgentBackend.MINI_SWE_AGENT:
        return _build_mini_swe_agent_invocation(model, docker_config)
    return BackendInvocation(
        model=model,
        env_passthrough=docker_config.env_passthrough,
        env_args=(),
        docker_args=docker_config.docker_args,
    )


def _build_opencode_invocation(model: str, docker_config: DockerAgentConfig) -> BackendInvocation:
    provider = docker_config.openai_compatible_provider
    if provider is None:
        return BackendInvocation(
            model=model,
            env_passthrough=docker_config.env_passthrough,
            env_args=(),
            docker_args=docker_config.docker_args,
        )
    return BackendInvocation(
        model=_resolve_opencode_model(model, provider),
        env_passthrough=_dedupe_strings((*docker_config.env_passthrough, provider.client.api_key_env or "")),
        env_args=tuple(_render_openai_compatible_provider_args(model, provider, docker_config.docker_args)),
        docker_args=_resolved_opencode_docker_args(docker_config.docker_args, provider),
    )


def _build_mini_swe_agent_invocation(model: str, docker_config: DockerAgentConfig) -> BackendInvocation:
    provider = docker_config.openai_compatible_provider
    if provider is None:
        return BackendInvocation(
            model=model,
            env_passthrough=docker_config.env_passthrough,
            env_args=(),
            docker_args=docker_config.docker_args,
        )
    assert provider.client.base_url is not None
    base_url = _container_base_url(provider.client.base_url, docker_config.docker_args)
    return BackendInvocation(
        model=_resolve_litellm_openai_model(model),
        env_passthrough=_dedupe_strings(
            (*docker_config.env_passthrough, provider.client.api_key_env or "", "OPENAI_API_KEY")
        ),
        env_args=(
            "-e",
            f"OPENAI_API_BASE={base_url}",
            "-e",
            f"OPENAI_BASE_URL={base_url}",
            "-e",
            "MSWEA_COST_TRACKING=ignore_errors",
        ),
        docker_args=_resolved_opencode_docker_args(docker_config.docker_args, provider),
    )


def _resolved_opencode_docker_args(
    docker_args: tuple[str, ...],
    provider: OpenAICompatibleProviderConfig,
) -> tuple[str, ...]:
    assert provider.client.base_url is not None
    if _uses_host_network(docker_args):
        return docker_args
    if not _requires_host_internal_alias(provider.client.base_url):
        return docker_args
    return _dedupe_strings((*docker_args, HOST_INTERNAL_DOCKER_ARG))


def _render_openai_compatible_provider_args(
    model: str,
    provider: OpenAICompatibleProviderConfig,
    docker_args: tuple[str, ...],
) -> list[str]:
    config_content = _render_openai_compatible_provider_config(model, provider, docker_args)
    return ["-e", f"{OPENCODE_CONFIG_ENV}={config_content}"]


def _render_openai_compatible_provider_config(
    model: str,
    provider: OpenAICompatibleProviderConfig,
    docker_args: tuple[str, ...],
) -> str:
    provider_model = _provider_model_id(model, provider.provider_id)
    rendered = {
        "$schema": OPENCODE_CONFIG_SCHEMA,
        "provider": {
            provider.provider_id: {
                "npm": OPENAI_COMPATIBLE_PACKAGE,
                "name": provider.name,
                "options": _render_openai_compatible_provider_options(provider, docker_args),
                "models": {
                    provider_model: {
                        "name": provider_model,
                        "limit": {
                            "context": provider.context_limit,
                            "output": provider.output_limit,
                        },
                    },
                },
            },
        },
    }
    return json.dumps(rendered, separators=(",", ":"))


def _render_openai_compatible_provider_options(
    provider: OpenAICompatibleProviderConfig,
    docker_args: tuple[str, ...],
) -> dict[str, str]:
    assert provider.client.base_url is not None
    options = {"baseURL": _container_base_url(provider.client.base_url, docker_args)}
    if provider.client.api_key_env is not None:
        options["apiKey"] = f"{{env:{provider.client.api_key_env}}}"
    return options


def _resolve_opencode_model(model: str, provider: OpenAICompatibleProviderConfig) -> str:
    if model.startswith(f"{provider.provider_id}/"):
        return model
    return f"{provider.provider_id}/{model}"


def _resolve_litellm_openai_model(model: str) -> str:
    if model.startswith("openai/"):
        return model
    return f"openai/{model}"


def _provider_model_id(model: str, provider_id: str) -> str:
    prefix = f"{provider_id}/"
    if model.startswith(prefix):
        return model.removeprefix(prefix)
    return model


def _container_base_url(base_url: str, docker_args: tuple[str, ...]) -> str:
    if _uses_host_network(docker_args):
        return base_url
    split = urlsplit(base_url)
    if split.hostname not in LOCALHOST_NAMES:
        return base_url
    netloc = _replace_hostname(split, HOST_INTERNAL_NAME)
    return urlunsplit(split._replace(netloc=netloc))


def _requires_host_internal_alias(base_url: str) -> bool:
    return urlsplit(base_url).hostname in LOCALHOST_NAMES


def _uses_host_network(docker_args: tuple[str, ...]) -> bool:
    return HOST_NETWORK_DOCKER_ARG in docker_args or ("--network" in docker_args and "host" in docker_args)


def _replace_hostname(split: SplitResult, hostname: str) -> str:
    port = f":{split.port}" if split.port is not None else ""
    if split.username is None:
        return f"{hostname}{port}"
    password = f":{split.password}" if split.password is not None else ""
    return f"{split.username}{password}@{hostname}{port}"


def _dedupe_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _prepare_git_worktree(repo_path: Path, worktree_dir: Path, base_sha: str) -> None:
    shutil.rmtree(worktree_dir, ignore_errors=True)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_checked(["git", "-C", str(repo_path), "worktree", "add", "--detach", str(worktree_dir), base_sha])


def _prepare_agent_worktree(
    repo_path: Path,
    base_snapshot_dir: Path,
    worktree_dir: Path,
    base_sha: str,
    strategy: WorktreeStrategy,
) -> None:
    if strategy == WorktreeStrategy.GIT_WORKTREE:
        _prepare_git_worktree(repo_path, worktree_dir, base_sha)
        return
    _prepare_cow_snapshot_worktree(repo_path, base_snapshot_dir, worktree_dir, base_sha)


def _prepare_cow_snapshot_worktree(
    repo_path: Path,
    base_snapshot_dir: Path,
    worktree_dir: Path,
    base_sha: str,
) -> None:
    _ensure_base_snapshot(repo_path, base_snapshot_dir, base_sha)
    shutil.rmtree(worktree_dir, ignore_errors=True)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(base_snapshot_dir, worktree_dir)
    _initialize_baseline_repo(worktree_dir)


def _ensure_base_snapshot(repo_path: Path, base_snapshot_dir: Path, base_sha: str) -> None:
    marker_path = base_snapshot_dir / ".k8s_guideline_bench_base_sha"
    if marker_path.exists() and marker_path.read_text(encoding="utf-8").strip() == base_sha:
        return
    shutil.rmtree(base_snapshot_dir, ignore_errors=True)
    base_snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    archive_path = base_snapshot_dir.parent / f"{base_snapshot_dir.name}.tar"
    archive_path.unlink(missing_ok=True)
    _run_checked(["git", "-C", str(repo_path), "archive", base_sha, "-o", str(archive_path)])
    base_snapshot_dir.mkdir(parents=True, exist_ok=True)
    _run_checked(["tar", "-xf", str(archive_path), "-C", str(base_snapshot_dir)])
    archive_path.unlink(missing_ok=True)
    _ = marker_path.write_text(f"{base_sha}\n", encoding="utf-8")


def _copy_tree(source_dir: Path, destination_dir: Path) -> None:
    result = subprocess.run(
        ["cp", "-cR", f"{source_dir}/.", str(destination_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    shutil.copytree(source_dir, destination_dir, dirs_exist_ok=True)


def _initialize_baseline_repo(worktree_dir: Path) -> None:
    _run_checked(["git", "-C", str(worktree_dir), "init"])
    _run_checked(["git", "-C", str(worktree_dir), "config", "user.name", "k8s-guideline-bench"])
    _run_checked(["git", "-C", str(worktree_dir), "config", "user.email", "k8s-guideline-bench@example.invalid"])
    _run_checked(["git", "-C", str(worktree_dir), "add", "."])
    _run_checked(["git", "-C", str(worktree_dir), "commit", "-m", "base"])


def _collect_predicted_patch(
    worktree_dir: Path,
    changed_files: tuple[str, ...],
    predicted_patch_path: Path,
) -> None:
    command = [
        "git",
        "-C",
        str(worktree_dir),
        "diff",
        "--no-color",
        "HEAD",
        "--",
        *changed_files,
    ]
    result = subprocess.run(command, capture_output=True, check=True)
    _ = predicted_patch_path.write_bytes(result.stdout)


def _run_checked(command: list[str]) -> None:
    _ = subprocess.run(command, capture_output=True, text=True, check=True)


def _write_run_metadata(
    output_dir: Path,
    instance: dataset_builder.DatasetInstance,
    config: AgentRunConfig,
    status: AgentRunStatus,
    started_at: dt.datetime,
    predicted_patch_path: Path,
    exit_code: int | None,
) -> None:
    finished_at = dt.datetime.now(tz=dt.UTC)
    predicted_patch_bytes = predicted_patch_path.stat().st_size if predicted_patch_path.exists() else 0
    metadata = AgentRunMetadata(
        status=status,
        model=config.model,
        context_strategy=config.context_strategy,
        pr_number=instance.detail.pr_number,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_seconds=(finished_at - started_at).total_seconds(),
        predicted_patch_bytes=predicted_patch_bytes,
        attached_context_files=tuple(context_file.bench_path for context_file in config.context_files),
        exit_code=exit_code,
    )
    _ = (output_dir / RUN_METADATA_FILENAME).write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _is_previous_run_skippable(metadata_path: Path) -> bool:
    """Return True when a previous run finished successfully or was already skipped."""
    if not metadata_path.exists():
        return False
    try:
        metadata_data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return False
    if not isinstance(metadata_data, dict):
        return False
    status_value = metadata_data.get("status")
    if not isinstance(status_value, str):
        return False
    try:
        status = AgentRunStatus(status_value)
    except ValueError:
        return False
    return status in {AgentRunStatus.COMPLETED, AgentRunStatus.SKIPPED}


def _read_predicted_patch(predicted_patch_path: Path) -> str:
    if not predicted_patch_path.exists():
        return ""
    return predicted_patch_path.read_text(encoding="utf-8")


def _completed_process_from_timeout(
    command: list[str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=AGENT_TIMEOUT_EXIT_CODE,
        stdout="",
        stderr=f"agent timed out after {timeout_seconds}s",
    )


def _normalize_agent_completed_process(
    completed: subprocess.CompletedProcess[str],
    config: AgentRunConfig,
) -> subprocess.CompletedProcess[str]:
    if config.docker.backend != AgentBackend.OPENCODE or completed.returncode != 0:
        return completed
    if not _opencode_reported_error(completed.stderr):
        return completed
    return subprocess.CompletedProcess(
        args=completed.args,
        returncode=AGENT_REPORTED_ERROR_EXIT_CODE,
        stdout=completed.stdout,
        stderr="\n".join(
            [
                completed.stderr.rstrip("\n"),
                "OpenCode reported an error despite exiting with code 0.",
            ],
        ),
    )


def _opencode_reported_error(stderr: str) -> bool:
    return any(line.startswith("Error: ") for line in stderr.splitlines())


def _render_docker_raw_response(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        [
            f"exit_code={completed.returncode}",
            "## stdout",
            completed.stdout.rstrip("\n"),
            "## stderr",
            completed.stderr.rstrip("\n"),
            "",
        ],
    )
