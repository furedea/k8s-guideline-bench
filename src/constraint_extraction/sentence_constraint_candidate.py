"""LLM-assisted atomic constraint candidate generation."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

import base
import normative_audit
import sentence_context_selection


class SentenceConstraintCandidateTask(base.FrozenModel):
    """One selected original that needs one draft constraint."""

    id: str
    source_span: str
    source_strength: tuple[str, ...]
    original: str


class SentenceConstraintCandidate(base.FrozenModel):
    """One draft constraint generated from a selected original."""

    id: str
    task_id: str
    source_span: str
    source_strength: tuple[str, ...]
    original: str
    constraint: str


class ConstraintCandidateRetryAttempt(base.FrozenModel):
    """One failed Codex candidate generation attempt that triggered a retry."""

    attempt: int
    task_ids: tuple[str, ...]
    reason: str
    details: tuple[str, ...] = ()


class SentenceConstraintCandidateReport(base.FrozenModel):
    """LLM draft constraint report."""

    candidates: tuple[SentenceConstraintCandidate, ...]
    retry_attempts: tuple[ConstraintCandidateRetryAttempt, ...] = ()


class ExistingConstraintCandidateReportValidation(base.FrozenModel):
    """Whether an existing constraint candidate report can be reused."""

    is_reusable: bool
    reason: str


class CodexConstraintCandidateError(RuntimeError):
    """`codex exec` failed while generating draft constraints."""

    def __init__(self, *, command: tuple[str, ...], returncode: int, stdout: str, stderr: str) -> None:
        message = f"codex exec failed with returncode={returncode}"
        if stderr.strip():
            message = f"{message}\n\nstderr:\n{stderr.strip()}"
        if stdout.strip():
            message = f"{message}\n\nstdout:\n{stdout.strip()}"
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SentenceConstraintCandidateRetryError(RuntimeError):
    """Codex kept returning incomplete or invalid draft constraints."""

    def __init__(self, *, attempts: tuple[ConstraintCandidateRetryAttempt, ...]) -> None:
        latest = attempts[-1]
        super().__init__(
            "sentence constraint candidate generation failed after retries: "
            f"attempt={latest.attempt} reason={latest.reason} task_ids={', '.join(latest.task_ids)}",
        )
        self.attempts = attempts


def build_constraint_candidate_tasks(
    sentence_tasks: tuple[normative_audit.SentenceSelectionTask, ...],
    context_report: sentence_context_selection.SentenceContextSelectionReport,
) -> tuple[SentenceConstraintCandidateTask, ...]:
    """Join sentence selection tasks with selected originals for candidate generation."""
    selections_by_task_id = {selection.task_id: selection for selection in context_report.selections}
    tasks: list[SentenceConstraintCandidateTask] = []
    for sentence_task in sentence_tasks:
        selection = selections_by_task_id[sentence_task.id]
        tasks.append(
            SentenceConstraintCandidateTask(
                id=sentence_task.id,
                source_span=sentence_task.source_span,
                source_strength=_source_strength(sentence_task.main_sentence.signal_tags),
                original=selection.original,
            ),
        )
    return tuple(tasks)


def load_constraint_candidate_report(path: Path) -> SentenceConstraintCandidateReport:
    """Load an atomic constraint candidate report."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("Constraint candidate report must contain a JSON object.")
    report_document = cast(dict[str, object], document)
    return SentenceConstraintCandidateReport(
        candidates=tuple(
            _constraint_candidate_from_json(candidate) for candidate in _list_field(report_document, "candidates")
        ),
        retry_attempts=tuple(
            _retry_attempt_from_json(attempt) for attempt in _list_field(report_document, "retry_attempts")
        ),
    )


def save_constraint_candidate_report(report: SentenceConstraintCandidateReport, output_path: Path) -> None:
    """Save atomic constraint candidate report as JSON."""
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_existing_report(
    report: SentenceConstraintCandidateReport,
    tasks: tuple[SentenceConstraintCandidateTask, ...],
) -> ExistingConstraintCandidateReportValidation:
    """Check whether an existing candidate report covers the current task set."""
    expected_task_ids = {task.id for task in tasks}
    candidate_task_ids = {candidate.task_id for candidate in report.candidates}
    missing_task_ids = expected_task_ids - candidate_task_ids
    if missing_task_ids:
        return ExistingConstraintCandidateReportValidation(is_reusable=False, reason="missing_task_candidates")
    extra_task_ids = candidate_task_ids - expected_task_ids
    if extra_task_ids:
        return ExistingConstraintCandidateReportValidation(is_reusable=False, reason="unknown_task_candidates")
    return ExistingConstraintCandidateReportValidation(is_reusable=True, reason="complete")


def select_constraint_candidates_with_codex(
    tasks: tuple[SentenceConstraintCandidateTask, ...],
    *,
    codex_command: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 1800,
    stream_output: bool = False,
    max_retries: int = 3,
    batch_size: int = 25,
) -> SentenceConstraintCandidateReport:
    """Run Codex in batches to generate one draft constraint for each original."""
    reports = tuple(
        _select_constraint_candidate_batch_with_codex(
            batch,
            codex_command=codex_command,
            model=model,
            timeout_seconds=timeout_seconds,
            stream_output=stream_output,
            max_retries=max_retries,
        )
        for batch in _task_batches(tasks, batch_size)
    )
    candidates_by_task_id = {
        task.id: tuple(
            candidate for report in reports for candidate in report.candidates if candidate.task_id == task.id
        )
        for task in tasks
    }
    return SentenceConstraintCandidateReport(
        candidates=tuple(candidate for task in tasks for candidate in candidates_by_task_id[task.id]),
        retry_attempts=tuple(retry_attempt for report in reports for retry_attempt in report.retry_attempts),
    )


def run_codex_constraint_candidates(
    prompt: str,
    *,
    codex_command: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 1800,
    stream_output: bool = False,
) -> str:
    """Invoke `codex exec` one-shot and return its final message."""
    with tempfile.TemporaryDirectory() as directory:
        temp_dir = Path(directory)
        output_path = temp_dir / "codex_last_message.txt"
        schema_path = temp_dir / "sentence_constraint_candidate.schema.json"
        schema_path.write_text(json.dumps(_CODEX_OUTPUT_SCHEMA, indent=2) + "\n", encoding="utf-8")
        command = [
            codex_command,
            "exec",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if model is not None:
            command.extend(("--model", model))
        command.append("-")
        if stream_output:
            completed = subprocess.run(
                command,
                input=prompt,
                stdout=None,
                stderr=None,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        else:
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        if completed.returncode != 0:
            raise CodexConstraintCandidateError(
                command=tuple(command),
                returncode=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
        if output_path.exists():
            return output_path.read_text(encoding="utf-8")
        return completed.stdout


def build_constraint_candidate_prompt(
    tasks: tuple[SentenceConstraintCandidateTask, ...],
    *,
    retry_feedback: tuple[ConstraintCandidateRetryAttempt, ...] = (),
) -> str:
    """Build a JSON-only draft constraint prompt."""
    task_payload = [
        {
            "task_id": task.id,
            "source_span": task.source_span,
            "source_strength": task.source_strength,
            "original": task.original,
        }
        for task in tasks
    ]
    retry_text = ""
    if retry_feedback:
        retry_payload = [attempt.model_dump(mode="json") for attempt in retry_feedback]
        retry_text = (
            "\nPrevious answer was invalid. Fix only the listed tasks and obey the validation feedback:\n"
            f"{json.dumps(retry_payload, ensure_ascii=False, indent=2)}\n"
        )
    return (
        "You are Codex. For each task, write exactly one draft constraint for each original.\n"
        "The draft must be concise, testable, and grounded only in the original.\n"
        "Do not split the original into multiple constraints. "
        "If the original contains multiple requirements, keep them in one draft constraint.\n"
        "A human reviewer will decide whether the draft is atomic. Do not add interpretations or explanations.\n"
        "Return JSON only with this schema:\n"
        '{"tasks":[{"task_id":"...","constraint":"..."}]}\n\n'
        f"{retry_text}"
        f"Tasks:\n{json.dumps({'tasks': task_payload}, ensure_ascii=False, indent=2)}"
    )


def _select_constraint_candidate_batch_with_codex(
    tasks: tuple[SentenceConstraintCandidateTask, ...],
    *,
    codex_command: str,
    model: str | None,
    timeout_seconds: int,
    stream_output: bool,
    max_retries: int,
) -> SentenceConstraintCandidateReport:
    tasks_by_id = {task.id: task for task in tasks}
    constraints_by_task_id: dict[str, str] = {}
    retry_attempts: list[ConstraintCandidateRetryAttempt] = []
    pending_tasks = tasks
    retry_feedback: tuple[ConstraintCandidateRetryAttempt, ...] = ()

    for attempt in range(1, max_retries + 2):
        response = run_codex_constraint_candidates(
            build_constraint_candidate_prompt(pending_tasks, retry_feedback=retry_feedback),
            codex_command=codex_command,
            model=model,
            timeout_seconds=timeout_seconds,
            stream_output=stream_output,
        )
        attempt_constraints, missing_task_ids, extra_task_ids = _parse_constraint_candidate_response(
            response,
            pending_tasks,
        )
        constraints_by_task_id.update(attempt_constraints)
        retry_feedback = _retry_attempts_for_validation(
            attempt=attempt,
            missing_task_ids=missing_task_ids,
            extra_task_ids=extra_task_ids,
        )
        if not retry_feedback and len(constraints_by_task_id) == len(tasks):
            break
        retry_attempts.extend(retry_feedback)
        retry_task_ids = _retry_task_ids(retry_feedback)
        for task_id in retry_task_ids:
            constraints_by_task_id.pop(task_id, None)
        if attempt > max_retries:
            raise SentenceConstraintCandidateRetryError(attempts=tuple(retry_attempts))
        pending_tasks = tuple(tasks_by_id[task_id] for task_id in retry_task_ids if task_id in tasks_by_id)
        if not pending_tasks:
            raise SentenceConstraintCandidateRetryError(attempts=tuple(retry_attempts))

    return SentenceConstraintCandidateReport(
        candidates=tuple(_materialize_candidate(task, constraints_by_task_id[task.id]) for task in tasks),
        retry_attempts=tuple(retry_attempts),
    )


def _materialize_candidate(
    task: SentenceConstraintCandidateTask,
    constraint: str,
) -> SentenceConstraintCandidate:
    return SentenceConstraintCandidate(
        id=task.id,
        task_id=task.id,
        source_span=task.source_span,
        source_strength=task.source_strength,
        original=task.original,
        constraint=constraint,
    )


def _task_batches(
    tasks: tuple[SentenceConstraintCandidateTask, ...],
    batch_size: int,
) -> tuple[tuple[SentenceConstraintCandidateTask, ...], ...]:
    if batch_size < 1:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    return tuple(tasks[index : index + batch_size] for index in range(0, len(tasks), batch_size))


def _parse_constraint_candidate_response(
    response: str,
    tasks: tuple[SentenceConstraintCandidateTask, ...],
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    document = json.loads(_extract_json_object(response))
    raw_tasks = document["tasks"]
    constraints_by_task_id: dict[str, str] = {}
    for item in raw_tasks:
        task_id = str(item["task_id"])
        constraints_by_task_id[task_id] = str(item["constraint"]).strip()

    expected_task_ids = {task.id for task in tasks}
    missing_task_ids = tuple(task_id for task_id in expected_task_ids if not constraints_by_task_id.get(task_id))
    extra_task_ids = tuple(task_id for task_id in constraints_by_task_id if task_id not in expected_task_ids)
    constraints_by_task_id = {
        task_id: constraints for task_id, constraints in constraints_by_task_id.items() if task_id in expected_task_ids
    }
    return constraints_by_task_id, missing_task_ids, extra_task_ids


def _retry_attempts_for_validation(
    *,
    attempt: int,
    missing_task_ids: tuple[str, ...],
    extra_task_ids: tuple[str, ...],
) -> tuple[ConstraintCandidateRetryAttempt, ...]:
    retry_attempts: list[ConstraintCandidateRetryAttempt] = []
    if missing_task_ids:
        retry_attempts.append(
            ConstraintCandidateRetryAttempt(
                attempt=attempt, task_ids=missing_task_ids, reason="missing_task_constraints"
            ),
        )
    if extra_task_ids:
        retry_attempts.append(
            ConstraintCandidateRetryAttempt(
                attempt=attempt, task_ids=(), reason="unknown_task_id", details=extra_task_ids
            ),
        )
    return tuple(retry_attempts)


def _retry_task_ids(retry_attempts: tuple[ConstraintCandidateRetryAttempt, ...]) -> tuple[str, ...]:
    task_ids: list[str] = []
    for retry_attempt in retry_attempts:
        task_ids.extend(retry_attempt.task_ids)
    return tuple(dict.fromkeys(task_ids))


def _source_strength(signal_tags: tuple[normative_audit.SignalTag, ...]) -> tuple[str, ...]:
    values = tuple(tag.value for tag in signal_tags)
    stronger_values = tuple(value for value in values if value != normative_audit.SignalTag.PERMISSIVE.value)
    return stronger_values or values


def _constraint_candidate_from_json(document: object) -> SentenceConstraintCandidate:
    if not isinstance(document, dict):
        raise TypeError("Constraint candidate document must be an object.")
    candidate_document = cast(dict[str, object], document)
    return SentenceConstraintCandidate(
        id=str(candidate_document["id"]),
        task_id=str(candidate_document["task_id"]),
        source_span=str(candidate_document["source_span"]),
        source_strength=tuple(str(item) for item in _list_field(candidate_document, "source_strength")),
        original=str(candidate_document["original"]),
        constraint=str(candidate_document["constraint"]),
    )


def _retry_attempt_from_json(document: object) -> ConstraintCandidateRetryAttempt:
    if not isinstance(document, dict):
        raise TypeError("Constraint candidate retry attempt document must be an object.")
    attempt_document = cast(dict[str, object], document)
    attempt = attempt_document["attempt"]
    if not isinstance(attempt, int):
        raise TypeError("Constraint candidate retry attempt `attempt` must be an integer.")
    return ConstraintCandidateRetryAttempt(
        attempt=attempt,
        task_ids=tuple(str(item) for item in _list_field(attempt_document, "task_ids")),
        reason=str(attempt_document["reason"]),
        details=tuple(str(item) for item in _list_field(attempt_document, "details")),
    )


def _list_field(document: dict[Any, Any], key: str) -> list[object]:
    value = document.get(key, [])
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array.")
    return value


def _extract_json_object(response: str) -> str:
    stripped = response.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if stripped.startswith("{"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response did not contain a JSON object.")
    return stripped[start : end + 1]


_CODEX_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tasks"],
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["task_id", "constraint"],
                "properties": {
                    "task_id": {"type": "string"},
                    "constraint": {"type": "string"},
                },
            },
        },
    },
}
