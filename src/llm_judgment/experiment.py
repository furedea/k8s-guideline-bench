"""Experiment orchestration: run agent + judge over a prebuilt dataset.

The experiment layer is intentionally decoupled from dataset construction.
`run_experiment` receives already-materialized `DatasetInstance`s along with
an `ExperimentSpec` (constraints, result root, agent/judge configs) and a
`client_factory` that resolves the judge `ClientSpec` into a live `CompletionClient`.
"""

import datetime as dt
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

import agent_runner
import atomic_constraint
import base
import client_spec
import completion_client
import dataset_builder
import error
import judge
import pydantic
import tqdm

logger = logging.getLogger(__name__)

ClientFactory = Callable[[client_spec.ClientSpec], completion_client.CompletionClient]


class ExperimentSpec(base.FrozenModel):
    """Top-level experiment configuration independent of dataset construction."""

    datasets_root: Path
    results_root: Path
    repo_path: Path
    constraints_file: Path
    instance_limit: int | None = None
    agent_configs: tuple[agent_runner.AgentRunConfig, ...]
    judge_config: judge.JudgeConfig

    @pydantic.field_validator("datasets_root", "results_root", "repo_path", "constraints_file", mode="before")
    @classmethod
    def validate_path_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("agent_configs", mode="before")
    @classmethod
    def validate_agent_configs(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[agent_runner.AgentRunConfig]", value))
        return value


class RunReport(base.FrozenModel):
    """Aggregate results for a single agent run configuration.

    Verdict tallies live in `summary` (constraint-level). Instance-level
    rollups (`instances_with_*`) count distinct dataset instances where any
    judgment hit the matching failure status, so a single bad patch does not
    inflate the score by its constraint count.
    """

    run_id: str
    model: str
    context_strategy: agent_runner.ContextStrategy
    instance_ids: tuple[str, ...]
    agent_completed: int = 0
    agent_failed: int = 0
    agent_skipped: int = 0
    summary: judge.JudgmentSummary
    instances_judged: int = 0
    instances_with_patch_apply_failure: int = 0
    instances_with_build_failure: int = 0
    instances_with_test_failure: int = 0
    instances_with_api_failure: int = 0

    @pydantic.field_validator("instance_ids", mode="before")
    @classmethod
    def validate_instance_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[str]", value))
        return value


class ExperimentReport(base.FrozenModel):
    """Top-level report bundling every agent run."""

    generated_at: str
    runs: tuple[RunReport, ...]

    @pydantic.field_validator("runs", mode="before")
    @classmethod
    def validate_runs(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[RunReport]", value))
        return value


def run_experiment(
    spec: ExperimentSpec,
    instances: tuple[dataset_builder.DatasetInstance, ...],
    client_factory: ClientFactory,
) -> ExperimentReport:
    """Run every agent config against the given dataset and judge each result.

    The judge client is instantiated once and shared across runs so subscription
    quotas are not burned by redundant factory calls.
    """
    constraints = atomic_constraint.load_atomic_constraints(spec.constraints_file)
    judge_client = client_factory(spec.judge_config.client)
    instance_ids = tuple(str(instance.detail.pr_number) for instance in instances)
    gold_patches = tuple(_load_gold_patch(instance) for instance in instances)
    logger.info(
        {
            "action": "experiment_start",
            "agent_runs": len(spec.agent_configs),
            "instances": len(instances),
            "constraints": len(constraints),
        }
    )
    runs = tuple(
        _execute_run(
            spec=spec,
            instances=instances,
            instance_ids=instance_ids,
            gold_patches=gold_patches,
            constraints=constraints,
            agent_config=agent_config,
            judge_client=judge_client,
            run_index=run_index,
            total_runs=len(spec.agent_configs),
        )
        for run_index, agent_config in enumerate(spec.agent_configs, start=1)
    )
    report = ExperimentReport(
        generated_at=dt.datetime.now(tz=dt.UTC).isoformat(),
        runs=runs,
    )
    _persist_report(report, spec.results_root)
    return report


_SPEC_ADAPTER = pydantic.TypeAdapter(ExperimentSpec)


def load_experiment_spec(spec_path: Path) -> ExperimentSpec:
    """Load an ExperimentSpec from a JSON file."""
    try:
        document = json.loads(spec_path.read_text(encoding="utf-8"))
        return _SPEC_ADAPTER.validate_python(document)
    except (OSError, json.JSONDecodeError, pydantic.ValidationError) as validation_error:
        raise error.ConstraintCatalogError(
            f"Invalid experiment spec in {spec_path}",
        ) from validation_error


def _execute_run(
    spec: ExperimentSpec,
    instances: tuple[dataset_builder.DatasetInstance, ...],
    instance_ids: tuple[str, ...],
    gold_patches: tuple[str, ...],
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    agent_config: agent_runner.AgentRunConfig,
    judge_client: completion_client.CompletionClient,
    run_index: int,
    total_runs: int,
) -> RunReport:
    logger.info(
        {
            "action": "run_start",
            "run_index": run_index,
            "total_runs": total_runs,
            "run_id": agent_config.run_id,
            "model": agent_config.model,
            "context_strategy": agent_config.context_strategy.value,
        }
    )
    agent_results = agent_runner.run_agent_on_instances(
        instances=instances,
        constraints=constraints,
        config=agent_config,
        results_root=spec.results_root,
        repo_path=spec.repo_path,
    )
    judged_inputs = tuple(
        (instance, gold_patch, agent_result)
        for instance, gold_patch, agent_result in zip(
            instances,
            gold_patches,
            agent_results,
            strict=True,
        )
        if agent_result.status != agent_runner.AgentRunStatus.FAILED
    )
    judge_progress = tqdm.tqdm(
        judged_inputs,
        desc=f"judge[{agent_config.run_id}]",
        unit="pr",
        ncols=88,
    )
    judgments = tuple(
        judge.judge_instance(
            instance=instance,
            predicted_patch=agent_result.predicted_patch,
            gold_patch=gold_patch,
            constraints=constraints,
            client=judge_client,
            config=spec.judge_config,
            run_id=agent_result.run_id,
            results_root=spec.results_root,
        )
        for instance, gold_patch, agent_result in judge_progress
    )
    summary = judge.summarize_judgments(judgments)
    instance_status_counts = _count_instances_per_status(judgments)
    logger.info(
        {
            "action": "run_done",
            "run_id": agent_config.run_id,
            "compliance_rate": summary.compliance_rate,
            "newly_satisfied_rate": summary.newly_satisfied_rate,
            "compliant": summary.compliant,
            "newly_satisfied": summary.newly_satisfied,
            "violated": summary.violated,
            "total": summary.total,
            "api_failure": summary.api_failure,
        }
    )
    return RunReport(
        run_id=agent_config.run_id,
        model=agent_config.model,
        context_strategy=agent_config.context_strategy,
        instance_ids=instance_ids,
        agent_completed=_count_agent_results(agent_results, agent_runner.AgentRunStatus.COMPLETED),
        agent_failed=_count_agent_results(agent_results, agent_runner.AgentRunStatus.FAILED),
        agent_skipped=_count_agent_results(agent_results, agent_runner.AgentRunStatus.SKIPPED),
        summary=summary,
        instances_judged=instance_status_counts[judge.JudgmentStatus.OK],
        instances_with_patch_apply_failure=instance_status_counts[judge.JudgmentStatus.PATCH_APPLY_FAILURE],
        instances_with_build_failure=instance_status_counts[judge.JudgmentStatus.BUILD_FAILURE],
        instances_with_test_failure=instance_status_counts[judge.JudgmentStatus.TEST_FAILURE],
        instances_with_api_failure=instance_status_counts[judge.JudgmentStatus.API_FAILURE],
    )


def _count_instances_per_status(
    judgments: tuple[judge.InstanceJudgment, ...],
) -> dict[judge.JudgmentStatus, int]:
    counts = dict.fromkeys(judge.JudgmentStatus, 0)
    for instance_judgment in judgments:
        for status in {j.status for j in instance_judgment.judgments}:
            counts[status] += 1
    return counts


def _count_agent_results(
    results: tuple[agent_runner.AgentRunResult, ...],
    status: agent_runner.AgentRunStatus,
) -> int:
    return sum(1 for result in results if result.status == status)


def _load_gold_patch(instance: dataset_builder.DatasetInstance) -> str:
    gold_patch_path = instance.root / dataset_builder.GOLD_PATCH_FILENAME
    try:
        return gold_patch_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _persist_report(report: ExperimentReport, results_root: Path) -> None:
    results_root.mkdir(parents=True, exist_ok=True)
    _ = (results_root / "experiment_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
