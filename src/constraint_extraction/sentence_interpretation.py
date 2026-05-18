"""LLM-assisted interpretation generation for draft constraints."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

import base
import sentence_constraint_candidate


class SentenceInterpretationTask(base.FrozenModel):
    """One draft constraint that needs a concise reviewer-facing interpretation."""

    id: str
    source_span: str
    source_strength: tuple[str, ...]
    original: str
    constraint: str


class SentenceInterpretation(base.FrozenModel):
    """A generated interpretation for one draft constraint."""

    task_id: str
    source_span: str
    source_strength: tuple[str, ...]
    original: str
    constraint: str
    interpretation: str


class InterpretationRetryAttempt(base.FrozenModel):
    """One failed Codex interpretation attempt that triggered a retry."""

    attempt: int
    task_ids: tuple[str, ...]
    reason: str
    details: tuple[str, ...] = ()


class SentenceInterpretationReport(base.FrozenModel):
    """LLM interpretation report for draft constraints."""

    interpretations: tuple[SentenceInterpretation, ...]
    retry_attempts: tuple[InterpretationRetryAttempt, ...] = ()


class ExistingInterpretationReportValidation(base.FrozenModel):
    """Whether an existing sentence interpretation report can be reused."""

    is_reusable: bool
    reason: str


class CodexInterpretationError(RuntimeError):
    """`codex exec` failed while generating source interpretations."""

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


class SentenceInterpretationRetryError(RuntimeError):
    """Codex kept returning incomplete or invalid interpretations."""

    def __init__(self, *, attempts: tuple[InterpretationRetryAttempt, ...]) -> None:
        latest = attempts[-1]
        super().__init__(
            "sentence interpretation failed after retries: "
            f"attempt={latest.attempt} reason={latest.reason} task_ids={', '.join(latest.task_ids)}",
        )
        self.attempts = attempts


def build_interpretation_tasks(
    draft_report: sentence_constraint_candidate.SentenceConstraintCandidateReport,
) -> tuple[SentenceInterpretationTask, ...]:
    """Build interpretation tasks from draft constraints."""
    return tuple(
        SentenceInterpretationTask(
            id=draft.id,
            source_span=draft.source_span,
            source_strength=draft.source_strength,
            original=draft.original,
            constraint=draft.constraint,
        )
        for draft in draft_report.candidates
    )


def load_interpretation_report(path: Path) -> SentenceInterpretationReport:
    """Load a sentence interpretation report."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("Sentence interpretation report must contain a JSON object.")
    report_document = cast(dict[str, object], document)
    return SentenceInterpretationReport(
        interpretations=tuple(
            _interpretation_from_json(interpretation)
            for interpretation in _list_field(report_document, "interpretations")
        ),
        retry_attempts=tuple(
            _retry_attempt_from_json(attempt) for attempt in _list_field(report_document, "retry_attempts")
        ),
    )


def save_interpretation_report(report: SentenceInterpretationReport, output_path: Path) -> None:
    """Save sentence interpretation report as JSON."""
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_existing_report(
    report: SentenceInterpretationReport,
    tasks: tuple[SentenceInterpretationTask, ...],
) -> ExistingInterpretationReportValidation:
    """Check whether an existing interpretation report fully covers the current task set."""
    expected_task_ids = {task.id for task in tasks}
    interpretation_task_ids = {interpretation.task_id for interpretation in report.interpretations}
    missing_task_ids = expected_task_ids - interpretation_task_ids
    if missing_task_ids:
        return ExistingInterpretationReportValidation(is_reusable=False, reason="missing_task_interpretations")
    extra_task_ids = interpretation_task_ids - expected_task_ids
    if extra_task_ids:
        return ExistingInterpretationReportValidation(is_reusable=False, reason="unknown_task_interpretations")
    return ExistingInterpretationReportValidation(is_reusable=True, reason="complete")


def select_interpretations_with_codex(
    tasks: tuple[SentenceInterpretationTask, ...],
    *,
    codex_command: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 1800,
    stream_output: bool = False,
    max_retries: int = 3,
    batch_size: int = 25,
) -> SentenceInterpretationReport:
    """Run Codex in batches to generate concise draft interpretations."""
    reports = tuple(
        _select_interpretation_batch_with_codex(
            batch,
            codex_command=codex_command,
            model=model,
            timeout_seconds=timeout_seconds,
            stream_output=stream_output,
            max_retries=max_retries,
        )
        for batch in _task_batches(tasks, batch_size)
    )
    interpretations_by_task_id = {
        interpretation.task_id: interpretation for report in reports for interpretation in report.interpretations
    }
    return SentenceInterpretationReport(
        interpretations=tuple(interpretations_by_task_id[task.id] for task in tasks),
        retry_attempts=tuple(retry_attempt for report in reports for retry_attempt in report.retry_attempts),
    )


def run_codex_interpretation(
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
        schema_path = temp_dir / "sentence_interpretation.schema.json"
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
            raise CodexInterpretationError(
                command=tuple(command),
                returncode=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
        if output_path.exists():
            return output_path.read_text(encoding="utf-8")
        return completed.stdout


def build_interpretation_prompt(
    tasks: tuple[SentenceInterpretationTask, ...],
    *,
    retry_feedback: tuple[InterpretationRetryAttempt, ...] = (),
) -> str:
    """Build a JSON-only interpretation prompt."""
    task_payload = [
        {
            "task_id": task.id,
            "source_span": task.source_span,
            "source_strength": task.source_strength,
            "original": task.original,
            "constraint": task.constraint,
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
        "You are Codex. For each task, interpret the normative meaning of the draft constraint.\n"
        "Write the interpretation in Japanese for human review.\n"
        "Use the original source text to keep the interpretation grounded.\n"
        "Do not invent requirements beyond the original and draft constraint. Do not split into atomic constraints.\n"
        "Keep each interpretation concise and concrete enough for a reviewer to judge grounding.\n"
        "Return JSON only with this schema:\n"
        '{"interpretations":[{"task_id":"...","interpretation":"..."}]}\n\n'
        f"{retry_text}"
        f"Tasks:\n{json.dumps({'tasks': task_payload}, ensure_ascii=False, indent=2)}"
    )


def _select_interpretation_batch_with_codex(
    tasks: tuple[SentenceInterpretationTask, ...],
    *,
    codex_command: str,
    model: str | None,
    timeout_seconds: int,
    stream_output: bool,
    max_retries: int,
) -> SentenceInterpretationReport:
    tasks_by_id = {task.id: task for task in tasks}
    interpretations_by_task_id: dict[str, str] = {}
    retry_attempts: list[InterpretationRetryAttempt] = []
    pending_tasks = tasks
    retry_feedback: tuple[InterpretationRetryAttempt, ...] = ()

    for attempt in range(1, max_retries + 2):
        response = run_codex_interpretation(
            build_interpretation_prompt(pending_tasks, retry_feedback=retry_feedback),
            codex_command=codex_command,
            model=model,
            timeout_seconds=timeout_seconds,
            stream_output=stream_output,
        )
        attempt_interpretations, missing_task_ids, extra_task_ids = _parse_interpretation_response(
            response,
            pending_tasks,
        )
        interpretations_by_task_id.update(attempt_interpretations)
        retry_feedback = _retry_attempts_for_validation(
            attempt=attempt,
            missing_task_ids=missing_task_ids,
            extra_task_ids=extra_task_ids,
        )
        if not retry_feedback and len(interpretations_by_task_id) == len(tasks):
            break
        retry_attempts.extend(retry_feedback)
        retry_task_ids = _retry_task_ids(retry_feedback)
        for task_id in retry_task_ids:
            interpretations_by_task_id.pop(task_id, None)
        if attempt > max_retries:
            raise SentenceInterpretationRetryError(attempts=tuple(retry_attempts))
        pending_tasks = tuple(tasks_by_id[task_id] for task_id in retry_task_ids if task_id in tasks_by_id)
        if not pending_tasks:
            raise SentenceInterpretationRetryError(attempts=tuple(retry_attempts))

    return SentenceInterpretationReport(
        interpretations=tuple(
            SentenceInterpretation(
                task_id=task.id,
                source_span=task.source_span,
                source_strength=task.source_strength,
                original=task.original,
                constraint=task.constraint,
                interpretation=interpretations_by_task_id[task.id],
            )
            for task in tasks
        ),
        retry_attempts=tuple(retry_attempts),
    )


def _task_batches(
    tasks: tuple[SentenceInterpretationTask, ...],
    batch_size: int,
) -> tuple[tuple[SentenceInterpretationTask, ...], ...]:
    if batch_size < 1:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    return tuple(tasks[index : index + batch_size] for index in range(0, len(tasks), batch_size))


def _parse_interpretation_response(
    response: str,
    tasks: tuple[SentenceInterpretationTask, ...],
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    document = json.loads(_extract_json_object(response))
    raw_interpretations = document["interpretations"]
    interpretations_by_task_id: dict[str, str] = {}
    for item in raw_interpretations:
        task_id = str(item["task_id"])
        interpretations_by_task_id[task_id] = str(item["interpretation"]).strip()

    expected_task_ids = {task.id for task in tasks}
    missing_task_ids = tuple(task_id for task_id in expected_task_ids if task_id not in interpretations_by_task_id)
    extra_task_ids = tuple(task_id for task_id in interpretations_by_task_id if task_id not in expected_task_ids)
    interpretations_by_task_id = {
        task_id: interpretation
        for task_id, interpretation in interpretations_by_task_id.items()
        if task_id in expected_task_ids
    }
    return interpretations_by_task_id, missing_task_ids, extra_task_ids


def _retry_attempts_for_validation(
    *,
    attempt: int,
    missing_task_ids: tuple[str, ...],
    extra_task_ids: tuple[str, ...],
) -> tuple[InterpretationRetryAttempt, ...]:
    retry_attempts: list[InterpretationRetryAttempt] = []
    if missing_task_ids:
        retry_attempts.append(
            InterpretationRetryAttempt(
                attempt=attempt, task_ids=missing_task_ids, reason="missing_task_interpretation"
            ),
        )
    if extra_task_ids:
        retry_attempts.append(
            InterpretationRetryAttempt(attempt=attempt, task_ids=(), reason="unknown_task_id", details=extra_task_ids),
        )
    return tuple(retry_attempts)


def _retry_task_ids(retry_attempts: tuple[InterpretationRetryAttempt, ...]) -> tuple[str, ...]:
    task_ids: list[str] = []
    for retry_attempt in retry_attempts:
        task_ids.extend(retry_attempt.task_ids)
    return tuple(dict.fromkeys(task_ids))


def _interpretation_from_json(document: object) -> SentenceInterpretation:
    if not isinstance(document, dict):
        raise TypeError("Sentence interpretation document must be an object.")
    interpretation_document = cast(dict[str, object], document)
    return SentenceInterpretation(
        task_id=str(interpretation_document["task_id"]),
        source_span=str(interpretation_document["source_span"]),
        source_strength=tuple(str(item) for item in _list_field(interpretation_document, "source_strength")),
        original=str(interpretation_document["original"]),
        constraint=str(interpretation_document["constraint"]),
        interpretation=str(interpretation_document["interpretation"]),
    )


def _retry_attempt_from_json(document: object) -> InterpretationRetryAttempt:
    if not isinstance(document, dict):
        raise TypeError("Interpretation retry attempt document must be an object.")
    attempt_document = cast(dict[str, object], document)
    attempt = attempt_document["attempt"]
    if not isinstance(attempt, int):
        raise TypeError("Interpretation retry attempt `attempt` must be an integer.")
    return InterpretationRetryAttempt(
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
    "required": ["interpretations"],
    "properties": {
        "interpretations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["task_id", "interpretation"],
                "properties": {
                    "task_id": {"type": "string"},
                    "interpretation": {"type": "string"},
                },
            },
        },
    },
}
