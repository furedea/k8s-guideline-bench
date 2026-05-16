import json
import subprocess
from pathlib import Path

import normative_audit
import sentence_constraint_candidate
import sentence_interpretation
from pytest_mock import MockerFixture


def test_build_interpretation_tasks_uses_draft_constraints() -> None:
    sentence_tasks = _sentence_tasks()
    draft_report = sentence_constraint_candidate.SentenceConstraintCandidateReport(
        candidates=(
            sentence_constraint_candidate.SentenceConstraintCandidate(
                id=sentence_tasks[0].id,
                task_id=sentence_tasks[0].id,
                source_span=sentence_tasks[0].source_span,
                source_strength=("obligation",),
                original="Optionality affects API compatibility. Fields must be either optional or required.",
                constraint="Fields must be either optional or required.",
            ),
        ),
    )

    tasks = sentence_interpretation.build_interpretation_tasks(draft_report)

    assert tasks[0].id == sentence_tasks[0].id
    assert tasks[0].source_span == sentence_tasks[0].source_span
    assert tasks[0].source_strength == ("obligation",)
    assert tasks[0].original == ("Optionality affects API compatibility. Fields must be either optional or required.")
    assert tasks[0].constraint == "Fields must be either optional or required."


def test_select_interpretations_with_codex_writes_one_interpretation_per_task(mocker: MockerFixture) -> None:
    tasks = _interpretation_tasks()
    codex_run = mocker.patch(
        "sentence_interpretation.run_codex_interpretation",
        side_effect=(
            json.dumps(
                {
                    "interpretations": [
                        {
                            "task_id": tasks[0].id,
                            "interpretation": "Fields must be either optional or required.",
                        },
                    ],
                },
            ),
            json.dumps(
                {
                    "interpretations": [
                        {
                            "task_id": tasks[1].id,
                            "interpretation": "New fields should explicitly set optional or required.",
                        },
                    ],
                },
            ),
        ),
    )

    report = sentence_interpretation.select_interpretations_with_codex(
        tasks,
        codex_command="codex",
        model="gpt-5.2",
        timeout_seconds=120,
        batch_size=1,
    )

    assert codex_run.call_count == 2
    assert "Return JSON only" in codex_run.call_args_list[0].args[0]
    assert codex_run.call_args_list[0].kwargs["model"] == "gpt-5.2"
    assert report.interpretations[0].interpretation == ("Fields must be either optional or required.")
    assert report.interpretations[1].source_strength == ("recommendation",)
    assert report.retry_attempts == ()


def test_select_interpretations_with_codex_retries_missing_task_selection(mocker: MockerFixture) -> None:
    tasks = _interpretation_tasks()
    mocker.patch(
        "sentence_interpretation.run_codex_interpretation",
        side_effect=(
            json.dumps(
                {
                    "interpretations": [
                        {"task_id": tasks[0].id, "interpretation": "A"},
                    ],
                },
            ),
            json.dumps(
                {
                    "interpretations": [
                        {"task_id": tasks[1].id, "interpretation": "B"},
                    ],
                },
            ),
        ),
    )

    report = sentence_interpretation.select_interpretations_with_codex(tasks, max_retries=1)

    assert tuple(item.task_id for item in report.interpretations) == tuple(task.id for task in tasks)
    assert report.retry_attempts[0].reason == "missing_task_interpretation"
    assert report.retry_attempts[0].task_ids == (tasks[1].id,)


def test_run_codex_interpretation_uses_schema_and_last_message(mocker: MockerFixture) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text('{"interpretations":[]}', encoding="utf-8")
        assert command[:2] == ["codex", "exec"]
        assert "--output-schema" in command
        assert command[-1] == "-"
        assert kwargs["input"] == "prompt"
        assert kwargs["timeout"] == 30
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    run = mocker.patch("sentence_interpretation.subprocess.run", side_effect=fake_run)

    response = sentence_interpretation.run_codex_interpretation(
        "prompt",
        codex_command="codex",
        model="gpt-5.2",
        timeout_seconds=30,
    )

    assert response == '{"interpretations":[]}'
    assert "--model" in run.call_args.args[0]


def test_load_and_save_interpretation_report(tmp_path: Path) -> None:
    output_path = tmp_path / "interpretations.json"
    report = sentence_interpretation.SentenceInterpretationReport(
        interpretations=(
            sentence_interpretation.SentenceInterpretation(
                task_id="block_0001_s1",
                source_span="10-10",
                source_strength=("obligation",),
                original="Fields must be either optional or required.",
                constraint="Fields must be either optional or required.",
                interpretation="Fields must be either optional or required.",
            ),
        ),
    )

    sentence_interpretation.save_interpretation_report(report, output_path)
    loaded = sentence_interpretation.load_interpretation_report(output_path)

    assert loaded == report


def _sentence_tasks() -> tuple[normative_audit.SentenceSelectionTask, ...]:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. New fields should explicitly set either `+optional` or `+required`.
""".strip()
    return normative_audit.extract_sentence_selection_tasks(document)


def _interpretation_tasks() -> tuple[sentence_interpretation.SentenceInterpretationTask, ...]:
    sentence_tasks = _sentence_tasks()
    return (
        sentence_interpretation.SentenceInterpretationTask(
            id=sentence_tasks[0].id,
            source_span=sentence_tasks[0].source_span,
            source_strength=("obligation",),
            original="Fields must be either optional or required.",
            constraint="Fields must be either optional or required.",
        ),
        sentence_interpretation.SentenceInterpretationTask(
            id=sentence_tasks[1].id,
            source_span=sentence_tasks[1].source_span,
            source_strength=("recommendation",),
            original="New fields should explicitly set either `+optional` or `+required`.",
            constraint="New fields should explicitly set either `+optional` or `+required`.",
        ),
    )
