"""LLM-as-a-Judge evaluator for AI-generated refactoring patches."""

import enum
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import atomic_constraint
import base
import client_spec
import completion_client
import dataset_builder
import pydantic
import tqdm
import verification as verification_module

logger = logging.getLogger(__name__)


class JudgeVerdict(enum.StrEnum):
    """Verdict emitted by the LLM judge for a single atomic constraint.

    `NOT_JUDGED` is the placeholder used when the judgment never produced a
    real verdict (e.g., parse / API / verification failure). Keeping the
    failure mode out of `NOT_APPLICABLE` lets summaries separate genuine
    "rule does not apply" answers from upstream failures.
    """

    COMPLIANT = "compliant"
    VIOLATED = "violated"
    NOT_APPLICABLE = "not_applicable"
    NOT_JUDGED = "not_judged"


class PatchEffect(enum.StrEnum):
    """Whether the predicted patch is responsible for satisfying the constraint.

    `NOT_APPLICABLE` covers verdicts whose constraint either does not apply
    (`verdict=not_applicable`) or is still violated (`verdict=violated`); both
    cases share that the patch effect is not meaningful. `NOT_JUDGED` is the
    placeholder used when the judgment itself never completed. `NOT_RELEVANT`
    is kept only for backward-compatible parsing of historical responses; it
    is normalized to `NOT_APPLICABLE` before storage.
    """

    APPLIED_BY_PATCH = "applied_by_patch"
    ALREADY_SATISFIED = "already_satisfied"
    NOT_APPLICABLE = "not_applicable"
    NOT_JUDGED = "not_judged"
    NOT_RELEVANT = "not_relevant"
    UNKNOWN = "unknown"


class JudgeMode(enum.StrEnum):
    """Whether the judge sees the human reference patch."""

    REFERENCE_BASED = "reference_based"
    PATCH_ONLY = "patch_only"


class JudgeTargetSelection(enum.StrEnum):
    """Which constraints to feed the judge for each instance.

    `ALL_CONSTRAINTS` evaluates the full catalog. `LLM_AND_HYBRID` skips
    `machine_checkable` constraints because static analysis is the right
    judge for them; sending such constraints to the LLM only adds noise.
    """

    ALL_CONSTRAINTS = "all_constraints"
    LLM_AND_HYBRID = "llm_and_hybrid"


class JudgmentStatus(enum.StrEnum):
    """Pipeline-level outcome of a single constraint judgment.

    `OK` means the LLM verdict is meaningful. Non-`OK` statuses mark failures
    upstream of the verdict (parse failure, API error, ...) so summaries can
    separate them from genuine `not_applicable` results.
    """

    OK = "ok"
    PARSE_FAILURE = "parse_failure"
    API_FAILURE = "api_failure"
    PATCH_APPLY_FAILURE = "patch_apply_failure"
    BUILD_FAILURE = "build_failure"
    TEST_FAILURE = "test_failure"


class PatchVerification(enum.StrEnum):
    """How aggressively to validate the predicted patch before judging.

    Each level subsumes the lighter ones: `BUILD` first runs `APPLY`, `TEST`
    runs `BUILD` then `go test`. Failure at any level short-circuits the LLM
    call and marks every selected constraint with the matching status.
    """

    NONE = "none"
    APPLY = "apply"
    BUILD = "build"
    TEST = "test"


class ConstraintJudgment(base.FrozenModel):
    """Per-constraint judgment result.

    Fields are ordered so the JSON dump puts pipeline metadata
    (`constraint_id`, `status`) first, the LLM-produced answer
    (`verdict`, `patch_effect`) next, and the supporting metrics
    (`confidence`, `rationale`) last.
    """

    constraint_id: str
    status: JudgmentStatus = JudgmentStatus.OK
    verdict: JudgeVerdict = JudgeVerdict.NOT_JUDGED
    patch_effect: PatchEffect = PatchEffect.NOT_JUDGED
    confidence: float = 0.0
    rationale: str = ""

    @pydantic.field_validator("verdict", mode="before")
    @classmethod
    def validate_verdict(cls, value: object) -> object:
        if isinstance(value, str):
            return JudgeVerdict(value)
        return value

    @pydantic.field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: object) -> object:
        if isinstance(value, str):
            return JudgmentStatus(value)
        return value

    @pydantic.field_validator("patch_effect", mode="before")
    @classmethod
    def validate_patch_effect(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = PatchEffect.NOT_APPLICABLE if value == PatchEffect.NOT_RELEVANT else PatchEffect(value)
            return normalized
        if value is PatchEffect.NOT_RELEVANT:
            return PatchEffect.NOT_APPLICABLE
        return value

    @pydantic.model_validator(mode="after")
    def normalize_judgment(self) -> ConstraintJudgment:
        if self.status != JudgmentStatus.OK:
            target_verdict = JudgeVerdict.NOT_JUDGED
            target_patch_effect = PatchEffect.NOT_JUDGED
            target_confidence = 0.0
        elif self.verdict == JudgeVerdict.COMPLIANT:
            target_verdict = self.verdict
            target_patch_effect = (
                self.patch_effect if self.patch_effect in _COMPLIANT_PATCH_EFFECTS else PatchEffect.UNKNOWN
            )
            target_confidence = self.confidence
        else:
            target_verdict = self.verdict
            target_patch_effect = PatchEffect.NOT_APPLICABLE
            target_confidence = self.confidence
        if (
            self.verdict == target_verdict
            and self.patch_effect == target_patch_effect
            and self.confidence == target_confidence
        ):
            return self
        object.__setattr__(self, "verdict", target_verdict)
        object.__setattr__(self, "patch_effect", target_patch_effect)
        object.__setattr__(self, "confidence", target_confidence)
        return self


class InstanceJudgment(base.FrozenModel):
    """Aggregate judgments for a single dataset instance under one run."""

    instance_id: str
    run_id: str
    judgments: tuple[ConstraintJudgment, ...]

    @pydantic.field_validator("judgments", mode="before")
    @classmethod
    def validate_judgments(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class JudgeConfig(base.FrozenModel):
    """Configuration for the judge LLM."""

    model: str
    max_tokens: int
    system_prompt: str
    client: client_spec.ClientSpec
    judge_mode: JudgeMode = JudgeMode.REFERENCE_BASED
    skip_existing: bool = False
    max_retries: int = 0
    max_workers: int = 4
    judge_target_selection: JudgeTargetSelection = JudgeTargetSelection.ALL_CONSTRAINTS
    patch_verification: PatchVerification = PatchVerification.NONE
    verification_timeout_seconds: float = 300.0

    @pydantic.field_validator("judge_mode", mode="before")
    @classmethod
    def validate_judge_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return JudgeMode(value)
        return value

    @pydantic.field_validator("judge_target_selection", mode="before")
    @classmethod
    def validate_judge_target_selection(cls, value: object) -> object:
        if isinstance(value, str):
            return JudgeTargetSelection(value)
        return value

    @pydantic.field_validator("patch_verification", mode="before")
    @classmethod
    def validate_patch_verification(cls, value: object) -> object:
        if isinstance(value, str):
            return PatchVerification(value)
        return value


class JudgmentSummary(base.FrozenModel):
    """Aggregate compliance metrics across instances.

    Verdict counters cover only `status=OK` judgments. Non-`OK` statuses are
    tallied separately so they do not pollute compliance / not_applicable.
    """

    total: int
    compliant: int
    violated: int
    not_applicable: int
    compliance_rate: float
    effective_total: int = 0
    newly_satisfied: int = 0
    newly_satisfied_rate: float = 0.0
    parse_failure: int = 0
    api_failure: int = 0
    patch_apply_failure: int = 0
    build_failure: int = 0
    test_failure: int = 0


DEFAULT_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial judge evaluating whether a code patch complies with a single "
    "atomic Kubernetes API convention rule. Respond strictly with a JSON object containing "
    "`verdict` (compliant | violated | not_applicable), "
    "`patch_effect` (applied_by_patch | already_satisfied | not_applicable | unknown), "
    "`confidence` (0..1), and `rationale`."
)


def build_judge_prompt(
    instance: dataset_builder.DatasetInstance,
    constraint: atomic_constraint.AtomicConstraint,
    predicted_patch: str,
    gold_patch: str,
    mode: JudgeMode = JudgeMode.REFERENCE_BASED,
) -> str:
    """Compose the user-facing prompt for a single-constraint judgment."""
    sections = [
        "## Atomic constraint",
        f"- id: {constraint.id}",
        f"- title: {constraint.title}",
        f"- rule: {constraint.rule}",
        f"- rationale: {constraint.rationale}",
        f"- judgeability: {constraint.judgeability.value}",
        f"- source: {constraint.source_path}:{constraint.source_span}",
        "",
        "## Task context",
        f"- pr: #{instance.detail.pr_number}",
        f"- title: {instance.detail.title}",
        f"- changed_files: {', '.join(instance.detail.changed_files)}",
        "",
        "## Predicted patch",
        "```diff",
        predicted_patch.rstrip("\n"),
        "```",
        "",
    ]
    if mode == JudgeMode.REFERENCE_BASED:
        sections.extend(
            [
                "## Gold patch (reference refactoring applied by the human author)",
                "```diff",
                gold_patch.rstrip("\n"),
                "```",
                "",
                "Evaluate whether the predicted patch is acceptable for the listed atomic constraint, "
                "using the gold patch as the human reference.",
            ],
        )
    else:
        sections.append("Evaluate whether the predicted patch complies with the listed atomic constraint.")
    sections.extend(
        [
            "Evaluate only the listed atomic constraint.",
            "Use `not_applicable` when the patch scope is outside the rule.",
            "Set `patch_effect=applied_by_patch` only when the predicted patch newly makes the "
            "constraint satisfied; use `already_satisfied` when the final code complies but the "
            "patch did not introduce that compliance.",
            'Return JSON: {"verdict": ..., "patch_effect": ..., "confidence": ..., "rationale": ...}.',
            "",
        ],
    )
    return "\n".join(sections)


_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\n(?P<body>.*?)```", flags=re.DOTALL)
_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", flags=re.DOTALL)


def parse_judge_response(response: str, constraint_id: str) -> ConstraintJudgment:
    """Parse a judge response into a structured judgment.

    Returns `status=PARSE_FAILURE` when the response cannot be parsed so the
    pipeline can keep running and the failure is visible in summaries
    distinct from genuine `not_applicable` verdicts. Verdict / patch_effect
    consistency (e.g., a non-compliant verdict implies `not_applicable`) is
    enforced by `ConstraintJudgment.normalize_judgment`.
    """
    payload = _extract_json_payload(response)
    if payload is None:
        return _failure_judgment(constraint_id, JudgmentStatus.PARSE_FAILURE, "Unparseable response.")
    try:
        document: dict[str, Any] = json.loads(payload)
        verdict = JudgeVerdict(document["verdict"])
        if verdict == JudgeVerdict.NOT_JUDGED:
            return _failure_judgment(constraint_id, JudgmentStatus.PARSE_FAILURE, "Verdict not_judged is reserved.")
        return ConstraintJudgment(
            constraint_id=constraint_id,
            verdict=verdict,
            confidence=float(document.get("confidence", 0.0)),
            rationale=str(document.get("rationale", "")),
            patch_effect=PatchEffect(document.get("patch_effect", PatchEffect.UNKNOWN.value)),
        )
    except ValueError, KeyError, pydantic.ValidationError:
        return _failure_judgment(constraint_id, JudgmentStatus.PARSE_FAILURE, "Malformed judge JSON.")


_COMPLIANT_PATCH_EFFECTS: frozenset[PatchEffect] = frozenset(
    {PatchEffect.APPLIED_BY_PATCH, PatchEffect.ALREADY_SATISFIED, PatchEffect.UNKNOWN},
)


def judge_instance(
    instance: dataset_builder.DatasetInstance,
    predicted_patch: str,
    gold_patch: str,
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    client: completion_client.CompletionClient,
    config: JudgeConfig,
    run_id: str,
    results_root: Path,
) -> InstanceJudgment:
    """Evaluate a single dataset instance against every atomic constraint.

    `run_id` scopes where judgments are persisted (alongside the agent run that
    produced `predicted_patch`), separate from judge-model configuration. When
    `config.skip_existing` is true the completed (`status=OK`) judgments from
    `judgments.json` and `judgments.partial.json` are reused per constraint;
    every constraint without an `OK` entry is re-judged. Each successful
    constraint is checkpointed to `judgments.partial.json` so an interrupted
    run can resume without redoing finished work.
    """
    instance_id = str(instance.detail.pr_number)
    selected = _select_constraints(constraints, config.judge_target_selection)
    completed = _load_completed_judgments(results_root, run_id, instance_id) if config.skip_existing else {}
    pending = tuple(constraint for constraint in selected if constraint.id not in completed)
    if not pending:
        return _finalize_instance_judgment(
            results_root,
            run_id,
            instance_id,
            tuple(completed[constraint.id] for constraint in selected),
        )
    _persist_judge_targets(results_root, run_id, instance_id, selected, config.judge_target_selection)
    new_judgments = _judge_pending_constraints(
        instance=instance,
        predicted_patch=predicted_patch,
        gold_patch=gold_patch,
        pending=pending,
        client=client,
        config=config,
        run_id=run_id,
        instance_id=instance_id,
        results_root=results_root,
        completed=completed,
    )
    merged = _merge_judgments(selected, completed, new_judgments)
    return _finalize_instance_judgment(results_root, run_id, instance_id, merged)


def _judge_pending_constraints(
    *,
    instance: dataset_builder.DatasetInstance,
    predicted_patch: str,
    gold_patch: str,
    pending: tuple[atomic_constraint.AtomicConstraint, ...],
    client: completion_client.CompletionClient,
    config: JudgeConfig,
    run_id: str,
    instance_id: str,
    results_root: Path,
    completed: dict[str, ConstraintJudgment],
) -> tuple[ConstraintJudgment, ...]:
    verification_failure = _verify_patch(
        instance,
        predicted_patch,
        config.patch_verification,
        config.verification_timeout_seconds,
    )
    if verification_failure is not None:
        return tuple(
            _failure_judgment(constraint.id, verification_failure.status, verification_failure.rationale)
            for constraint in pending
        )
    checkpoint = _PartialCheckpoint(
        path=_partial_judgments_path(results_root, run_id, instance_id),
        instance_id=instance_id,
        run_id=run_id,
        seed=completed,
    )
    return _judge_constraints_parallel(
        instance,
        predicted_patch,
        gold_patch,
        pending,
        client,
        config,
        run_id,
        instance_id,
        checkpoint=checkpoint,
    )


def _merge_judgments(
    selected: tuple[atomic_constraint.AtomicConstraint, ...],
    completed: dict[str, ConstraintJudgment],
    new_judgments: tuple[ConstraintJudgment, ...],
) -> tuple[ConstraintJudgment, ...]:
    new_by_id = {judgment.constraint_id: judgment for judgment in new_judgments}
    merged: list[ConstraintJudgment] = []
    for constraint in selected:
        if constraint.id in new_by_id:
            merged.append(new_by_id[constraint.id])
        else:
            merged.append(completed[constraint.id])
    return tuple(merged)


def _finalize_instance_judgment(
    results_root: Path,
    run_id: str,
    instance_id: str,
    judgments: tuple[ConstraintJudgment, ...],
) -> InstanceJudgment:
    result = InstanceJudgment(instance_id=instance_id, run_id=run_id, judgments=judgments)
    _persist_instance_judgment(result, results_root)
    return result


def summarize_judgments(results: tuple[InstanceJudgment, ...]) -> JudgmentSummary:
    """Aggregate verdict counts and overall compliance rate across instances.

    Only `status=OK` judgments contribute to verdict counters; other statuses
    are tallied into their own buckets so failure modes stay observable.
    """
    verdict_counts = dict.fromkeys(JudgeVerdict, 0)
    status_counts = dict.fromkeys(JudgmentStatus, 0)
    total = 0
    newly_satisfied = 0
    for result in results:
        for judgment in result.judgments:
            total += 1
            status_counts[judgment.status] += 1
            if judgment.status == JudgmentStatus.OK:
                verdict_counts[judgment.verdict] += 1
                if _is_newly_satisfied(judgment):
                    newly_satisfied += 1
    compliant = verdict_counts[JudgeVerdict.COMPLIANT]
    violated = verdict_counts[JudgeVerdict.VIOLATED]
    effective_total = compliant + violated
    compliance_rate = compliant / effective_total if effective_total else 0.0
    newly_satisfied_rate = newly_satisfied / effective_total if effective_total else 0.0
    return JudgmentSummary(
        total=total,
        compliant=compliant,
        violated=violated,
        not_applicable=verdict_counts[JudgeVerdict.NOT_APPLICABLE],
        compliance_rate=compliance_rate,
        effective_total=effective_total,
        newly_satisfied=newly_satisfied,
        newly_satisfied_rate=newly_satisfied_rate,
        parse_failure=status_counts[JudgmentStatus.PARSE_FAILURE],
        api_failure=status_counts[JudgmentStatus.API_FAILURE],
        patch_apply_failure=status_counts[JudgmentStatus.PATCH_APPLY_FAILURE],
        build_failure=status_counts[JudgmentStatus.BUILD_FAILURE],
        test_failure=status_counts[JudgmentStatus.TEST_FAILURE],
    )


def _is_newly_satisfied(judgment: ConstraintJudgment) -> bool:
    return judgment.verdict == JudgeVerdict.COMPLIANT and judgment.patch_effect == PatchEffect.APPLIED_BY_PATCH


class _PartialCheckpoint:
    """Thread-safe writer for `judgments.partial.json` that preserves OK results.

    Only `status=JudgmentStatus.OK` constraints are recorded so an
    interrupted run resumes from clean, reusable state without dragging
    transient API / parse failures forward.
    """

    __slots__ = ("_completed", "_instance_id", "_lock", "_path", "_run_id")

    def __init__(
        self,
        *,
        path: Path,
        instance_id: str,
        run_id: str,
        seed: dict[str, ConstraintJudgment],
    ) -> None:
        self._lock = threading.Lock()
        self._path = path
        self._instance_id = instance_id
        self._run_id = run_id
        self._completed: dict[str, ConstraintJudgment] = {
            constraint_id: judgment for constraint_id, judgment in seed.items() if judgment.status == JudgmentStatus.OK
        }

    def record(self, judgment: ConstraintJudgment) -> None:
        if judgment.status != JudgmentStatus.OK:
            return
        with self._lock:
            self._completed[judgment.constraint_id] = judgment
            self._flush_locked()

    def _flush_locked(self) -> None:
        ordered_ids = sorted(self._completed)
        document = {
            "instance_id": self._instance_id,
            "run_id": self._run_id,
            "judgments": [self._completed[constraint_id].model_dump(mode="json") for constraint_id in ordered_ids],
        }
        _atomic_write_json(self._path, document)


def _judge_single_constraint(
    instance: dataset_builder.DatasetInstance,
    constraint: atomic_constraint.AtomicConstraint,
    predicted_patch: str,
    gold_patch: str,
    client: completion_client.CompletionClient,
    config: JudgeConfig,
) -> ConstraintJudgment:
    prompt = build_judge_prompt(instance, constraint, predicted_patch, gold_patch, mode=config.judge_mode)
    last_error: Exception | None = None
    for _ in range(config.max_retries + 1):
        try:
            response = client.complete(
                system=config.system_prompt,
                user=prompt,
                model=config.model,
                max_tokens=config.max_tokens,
            )
        except Exception as exc:
            last_error = exc
            continue
        return parse_judge_response(response, constraint.id)
    logger.warning(
        {
            "action": "judge_api_failed",
            "constraint_id": constraint.id,
            "attempts": config.max_retries + 1,
            "error": str(last_error),
        }
    )
    return _failure_judgment(
        constraint.id,
        JudgmentStatus.API_FAILURE,
        f"Judge API failure: {last_error}",
    )


def _judge_constraints_parallel(
    instance: dataset_builder.DatasetInstance,
    predicted_patch: str,
    gold_patch: str,
    selected: tuple[atomic_constraint.AtomicConstraint, ...],
    client: completion_client.CompletionClient,
    config: JudgeConfig,
    run_id: str,
    instance_id: str,
    *,
    checkpoint: _PartialCheckpoint | None = None,
) -> tuple[ConstraintJudgment, ...]:
    workers = max(config.max_workers, 1)
    if workers == 1:
        progress = tqdm.tqdm(
            selected,
            desc=f"judge[{run_id}/{instance_id}]",
            unit="rule",
            ncols=88,
            leave=False,
        )
        judgments_list: list[ConstraintJudgment] = []
        for constraint in progress:
            judgment = _judge_single_constraint(instance, constraint, predicted_patch, gold_patch, client, config)
            judgments_list.append(judgment)
            if checkpoint is not None:
                checkpoint.record(judgment)
        return tuple(judgments_list)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_constraint = {
            executor.submit(
                _judge_single_constraint,
                instance,
                constraint,
                predicted_patch,
                gold_patch,
                client,
                config,
            ): constraint
            for constraint in selected
        }
        progress = tqdm.tqdm(
            as_completed(future_to_constraint),
            total=len(selected),
            desc=f"judge[{run_id}/{instance_id}]",
            unit="rule",
            ncols=88,
            leave=False,
        )
        judgments_list = []
        for future in progress:
            judgment = future.result()
            judgments_list.append(judgment)
            if checkpoint is not None:
                checkpoint.record(judgment)
    judgments_list.sort(key=lambda j: j.constraint_id)
    return tuple(judgments_list)


_INSTANCE_JUDGMENT_ADAPTER = pydantic.TypeAdapter(InstanceJudgment)
_CONSTRAINT_JUDGMENT_ADAPTER = pydantic.TypeAdapter(ConstraintJudgment)


def _judgments_path(results_root: Path, run_id: str, instance_id: str) -> Path:
    return results_root / run_id / instance_id / "judgments.json"


def _partial_judgments_path(results_root: Path, run_id: str, instance_id: str) -> Path:
    return results_root / run_id / instance_id / "judgments.partial.json"


def _judge_targets_path(results_root: Path, run_id: str, instance_id: str) -> Path:
    return results_root / run_id / instance_id / "judge_targets.json"


def _select_constraints(
    constraints: tuple[atomic_constraint.AtomicConstraint, ...],
    selection: JudgeTargetSelection,
) -> tuple[atomic_constraint.AtomicConstraint, ...]:
    if selection == JudgeTargetSelection.LLM_AND_HYBRID:
        return tuple(
            constraint
            for constraint in constraints
            if constraint.judgeability != atomic_constraint.Judgeability.MACHINE_CHECKABLE
        )
    return constraints


def _persist_judge_targets(
    results_root: Path,
    run_id: str,
    instance_id: str,
    selected: tuple[atomic_constraint.AtomicConstraint, ...],
    selection: JudgeTargetSelection,
) -> None:
    _write_json(
        _judge_targets_path(results_root, run_id, instance_id),
        {
            "selection": selection.value,
            "constraint_ids": [constraint.id for constraint in selected],
        },
    )


def _persist_instance_judgment(result: InstanceJudgment, results_root: Path) -> None:
    _write_json(
        _judgments_path(results_root, result.run_id, result.instance_id),
        result.model_dump(mode="json"),
    )


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(document, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            _ = handle.write(serialized)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _load_completed_judgments(
    results_root: Path,
    run_id: str,
    instance_id: str,
) -> dict[str, ConstraintJudgment]:
    """Return ok-only judgments keyed by constraint_id from final and partial files.

    Both `judgments.json` and `judgments.partial.json` are scanned. When the
    same constraint appears in both, the entry from `judgments.json` wins
    because it was committed at the end of a complete run.
    """
    completed: dict[str, ConstraintJudgment] = {}
    for path in (
        _partial_judgments_path(results_root, run_id, instance_id),
        _judgments_path(results_root, run_id, instance_id),
    ):
        for judgment in _read_constraint_judgments(path):
            if judgment.status == JudgmentStatus.OK:
                completed[judgment.constraint_id] = judgment
    return completed


def _read_constraint_judgments(path: Path) -> tuple[ConstraintJudgment, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, json.JSONDecodeError:
        return ()
    raw_judgments = document.get("judgments") if isinstance(document, dict) else document
    if not isinstance(raw_judgments, list):
        return ()
    parsed: list[ConstraintJudgment] = []
    for raw in raw_judgments:
        try:
            parsed.append(_CONSTRAINT_JUDGMENT_ADAPTER.validate_python(raw))
        except pydantic.ValidationError:
            continue
    return tuple(parsed)


def _extract_json_payload(response: str) -> str | None:
    fence_match = _JSON_FENCE_PATTERN.search(response)
    if fence_match is not None:
        return fence_match.group("body").strip()
    object_match = _JSON_OBJECT_PATTERN.search(response)
    if object_match is not None:
        return object_match.group(0).strip()
    return None


def _failure_judgment(constraint_id: str, status: JudgmentStatus, rationale: str) -> ConstraintJudgment:
    return ConstraintJudgment(
        constraint_id=constraint_id,
        status=status,
        verdict=JudgeVerdict.NOT_JUDGED,
        patch_effect=PatchEffect.NOT_JUDGED,
        confidence=0.0,
        rationale=rationale,
    )


class VerificationFailure(base.FrozenModel):
    """Reason a verification step rejected the predicted patch."""

    status: JudgmentStatus
    rationale: str


_GO_STEP_STATUS: dict[str, JudgmentStatus] = {
    "build": JudgmentStatus.BUILD_FAILURE,
    "test": JudgmentStatus.TEST_FAILURE,
}


def _verify_patch(
    instance: dataset_builder.DatasetInstance,
    predicted_patch: str,
    verification: PatchVerification,
    timeout_seconds: float,
) -> VerificationFailure | None:
    if verification == PatchVerification.NONE:
        return None
    precondition_failure = _check_verification_preconditions(instance, predicted_patch)
    if precondition_failure is not None:
        return precondition_failure
    return _run_verification_pipeline(instance, predicted_patch, verification, timeout_seconds)


def _check_verification_preconditions(
    instance: dataset_builder.DatasetInstance,
    predicted_patch: str,
) -> VerificationFailure | None:
    base_dir = instance.root / "base"
    if not base_dir.is_dir():
        return VerificationFailure(
            status=JudgmentStatus.PATCH_APPLY_FAILURE,
            rationale=f"Missing base/ directory at {base_dir}.",
        )
    if not predicted_patch.strip():
        return VerificationFailure(
            status=JudgmentStatus.PATCH_APPLY_FAILURE,
            rationale="Empty predicted patch.",
        )
    return None


def _run_verification_pipeline(
    instance: dataset_builder.DatasetInstance,
    predicted_patch: str,
    verification: PatchVerification,
    timeout_seconds: float,
) -> VerificationFailure | None:
    base_dir = instance.root / "base"
    packages = verification_module.derive_go_packages(instance.detail.changed_files)
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        shutil.copytree(base_dir, workdir, dirs_exist_ok=True)
        _init_temporary_repo(workdir)
        patch_path = workdir / "_predicted.patch"
        _ = patch_path.write_text(predicted_patch, encoding="utf-8")
        apply_failure = _check_patch_applies(workdir, patch_path)
        if apply_failure is not None or verification == PatchVerification.APPLY:
            return apply_failure
        _apply_patch(workdir, patch_path)
        build_failure = _run_go_step("build", workdir=workdir, packages=packages, timeout=timeout_seconds)
        if build_failure is not None or verification == PatchVerification.BUILD:
            return build_failure
        return _run_go_step("test", workdir=workdir, packages=packages, timeout=timeout_seconds)


def _check_patch_applies(workdir: Path, patch_path: Path) -> VerificationFailure | None:
    result = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=workdir,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    return VerificationFailure(
        status=JudgmentStatus.PATCH_APPLY_FAILURE,
        rationale=f"git apply --check failed: {result.stderr.decode('utf-8', errors='replace').strip()}",
    )


def _apply_patch(workdir: Path, patch_path: Path) -> None:
    _ = subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=workdir,
        check=True,
        capture_output=True,
    )


def _run_go_step(
    subcommand: str,
    *,
    workdir: Path,
    packages: tuple[str, ...],
    timeout: float,
) -> VerificationFailure | None:
    if not packages:
        return None
    failure_status = _GO_STEP_STATUS[subcommand]
    label = f"go {subcommand}"
    try:
        result = subprocess.run(
            ["go", subcommand, *packages],
            cwd=workdir,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return VerificationFailure(
            status=failure_status,
            rationale=f"{label} timed out after {timeout:.0f}s.",
        )
    if result.returncode == 0:
        return None
    stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else result.stderr
    return VerificationFailure(
        status=failure_status,
        rationale=f"{label} failed: {stderr.strip()[:1024]}",
    )


def _init_temporary_repo(workdir: Path) -> None:
    common_args = [
        "-c",
        "user.email=judge@example.invalid",
        "-c",
        "user.name=judge",
    ]
    _ = subprocess.run(["git", "init", "-q"], cwd=workdir, check=True, capture_output=True)
    _ = subprocess.run(["git", *common_args, "add", "-A"], cwd=workdir, check=True, capture_output=True)
    _ = subprocess.run(
        ["git", *common_args, "commit", "-q", "--allow-empty", "-m", "base"],
        cwd=workdir,
        check=True,
        capture_output=True,
    )
