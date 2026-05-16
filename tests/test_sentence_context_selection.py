import json
import subprocess
from pathlib import Path

import normative_audit
import sentence_context_selection
from pytest_mock import MockerFixture


def test_select_sentence_contexts_with_codex_materializes_original_and_detects_conflicts(
    mocker: MockerFixture,
) -> None:
    tasks = _tasks()
    codex_run = mocker.patch(
        "sentence_context_selection.run_codex_context_selection",
        return_value=json.dumps(
            {
                "selections": [
                    {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1", "s3"]},
                    {"task_id": tasks[1].id, "selected_context_sentence_ids": ["s1"]},
                ],
            },
        ),
    )

    report = sentence_context_selection.select_sentence_contexts_with_codex(
        tasks,
        codex_command="codex",
        model="gpt-5.2",
        timeout_seconds=120,
    )

    codex_run.assert_called_once()
    assert "Return JSON only" in codex_run.call_args.args[0]
    assert codex_run.call_args.kwargs["model"] == "gpt-5.2"
    assert codex_run.call_args.kwargs["timeout_seconds"] == 120
    assert report.selections[0].original == (
        "Optionality affects API compatibility. "
        "Fields must be either optional or required. "
        "This avoids ambiguous client behavior."
    )
    assert report.conflicts == ()


def test_select_sentence_contexts_with_codex_retries_missing_task_selection(mocker: MockerFixture) -> None:
    tasks = _tasks()
    codex_run = mocker.patch(
        "sentence_context_selection.run_codex_context_selection",
        side_effect=(
            json.dumps(
                {
                    "selections": [
                        {"task_id": tasks[0].id, "selected_context_sentence_ids": []},
                    ],
                },
            ),
            json.dumps(
                {
                    "selections": [
                        {"task_id": tasks[1].id, "selected_context_sentence_ids": []},
                    ],
                },
            ),
        ),
    )

    report = sentence_context_selection.select_sentence_contexts_with_codex(tasks)

    assert codex_run.call_count == 2
    assert report.retry_attempts[0].reason == "missing_task_selection"
    assert report.retry_attempts[0].task_ids == (tasks[1].id,)
    assert len(report.selections) == 2


def test_select_sentence_contexts_with_codex_retries_unknown_context_ids(
    mocker: MockerFixture,
) -> None:
    tasks = _tasks()
    codex_run = mocker.patch(
        "sentence_context_selection.run_codex_context_selection",
        side_effect=(
            json.dumps(
                {
                    "selections": [
                        {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1", "s99"]},
                        {"task_id": tasks[1].id, "selected_context_sentence_ids": ["s1"]},
                    ],
                },
            ),
            json.dumps(
                {
                    "selections": [
                        {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1"]},
                    ],
                },
            ),
        ),
    )

    report = sentence_context_selection.select_sentence_contexts_with_codex(tasks)

    assert codex_run.call_count == 2
    assert report.selections[0].selected_context_sentence_ids == ("s1",)
    assert report.invalid_context_selections == ()
    assert report.retry_attempts[0].task_ids == (tasks[0].id,)
    assert report.retry_attempts[0].reason == "unknown_context_sentence_id"
    assert report.retry_attempts[0].details == ("s99",)


def test_select_sentence_contexts_with_codex_retries_context_conflicts(mocker: MockerFixture) -> None:
    tasks = _tasks()
    mocker.patch(
        "sentence_context_selection.run_codex_context_selection",
        side_effect=(
            json.dumps(
                {
                    "selections": [
                        {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1", "s3"]},
                        {"task_id": tasks[1].id, "selected_context_sentence_ids": ["s1", "s3"]},
                    ],
                },
            ),
            json.dumps(
                {
                    "selections": [
                        {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1", "s3"]},
                        {"task_id": tasks[1].id, "selected_context_sentence_ids": ["s1"]},
                    ],
                },
            ),
        ),
    )

    report = sentence_context_selection.select_sentence_contexts_with_codex(tasks)

    assert report.conflicts == ()
    assert report.retry_attempts[0].reason == "context_selection_conflict"
    assert report.retry_attempts[0].task_ids == (tasks[0].id, tasks[1].id)
    assert report.retry_attempts[0].details == ("s3",)


def test_select_sentence_contexts_with_codex_fails_after_retry_limit(mocker: MockerFixture) -> None:
    tasks = _tasks()
    mocker.patch(
        "sentence_context_selection.run_codex_context_selection",
        return_value=json.dumps(
            {
                "selections": [
                    {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s99"]},
                    {"task_id": tasks[1].id, "selected_context_sentence_ids": []},
                ],
            },
        ),
    )

    try:
        _ = sentence_context_selection.select_sentence_contexts_with_codex(tasks, max_retries=1)
    except sentence_context_selection.SentenceContextSelectionRetryError as exc:
        assert exc.attempts[-1].attempt == 2
        assert exc.attempts[-1].reason == "unknown_context_sentence_id"
    else:
        raise AssertionError("Expected retry exhaustion to fail")


def test_run_codex_context_selection_captures_output_by_default(
    mocker: MockerFixture,
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text('{"selections":[]}', encoding="utf-8")
        assert command[:2] == ["codex", "exec"]
        assert "--ask-for-approval" not in command
        assert "--output-schema" in command
        assert command[-1] == "-"
        assert kwargs["input"] == "prompt"
        assert kwargs["timeout"] == 30
        assert kwargs["capture_output"] is True
        assert "stdout" not in kwargs
        assert "stderr" not in kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    run = mocker.patch("sentence_context_selection.subprocess.run", side_effect=fake_run)

    response = sentence_context_selection.run_codex_context_selection(
        "prompt",
        codex_command="codex",
        model="gpt-5.2",
        timeout_seconds=30,
    )

    assert response == '{"selections":[]}'
    assert "--model" in run.call_args.args[0]


def test_run_codex_context_selection_can_stream_codex_output(mocker: MockerFixture) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text('{"selections":[]}', encoding="utf-8")
        assert kwargs["stdout"] is None
        assert kwargs["stderr"] is None
        assert "capture_output" not in kwargs
        return subprocess.CompletedProcess(command, 0, stdout="out", stderr="err")

    mocker.patch("sentence_context_selection.subprocess.run", side_effect=fake_run)

    response = sentence_context_selection.run_codex_context_selection(
        "prompt",
        stream_output=True,
    )

    assert response == '{"selections":[]}'


def test_run_codex_context_selection_raises_on_non_zero_exit(mocker: MockerFixture) -> None:
    mocker.patch(
        "sentence_context_selection.subprocess.run",
        return_value=subprocess.CompletedProcess(["codex"], 2, stdout="out", stderr="err"),
    )

    try:
        _ = sentence_context_selection.run_codex_context_selection("prompt")
    except sentence_context_selection.CodexContextSelectionError as exc:
        assert exc.command[:4] == ("codex", "exec", "--sandbox", "read-only")
        assert "--output-schema" in exc.command
        assert exc.returncode == 2
        assert exc.stdout == "out"
        assert exc.stderr == "err"
        assert "stderr:\nerr" in str(exc)
    else:
        raise AssertionError("Expected codex failure to raise")


def test_load_and_save_sentence_context_selection_report(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    output_path = tmp_path / "selection.json"
    tasks = _tasks()
    tasks_path.write_text(
        json.dumps({"tasks": [task.model_dump(mode="json") for task in tasks]}),
        encoding="utf-8",
    )
    loaded_tasks = sentence_context_selection.load_sentence_selection_tasks(tasks_path)
    report = sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            sentence_context_selection.SentenceContextSelection(
                task_id=loaded_tasks[0].id,
                selected_context_sentence_ids=("s1",),
                original="Optionality affects API compatibility. Fields must be either optional or required.",
            ),
        ),
        conflicts=(),
    )

    sentence_context_selection.save_context_selection_report(report, output_path)

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["selections"][0]["task_id"] == loaded_tasks[0].id
    assert saved["selections"][0]["selected_context_sentence_ids"] == ["s1"]


def test_validate_existing_report_accepts_complete_report_with_retry_history() -> None:
    tasks = _tasks()
    report = sentence_context_selection.SentenceContextSelectionReport(
        selections=tuple(
            sentence_context_selection.SentenceContextSelection(
                task_id=task.id,
                selected_context_sentence_ids=(),
                original=task.main_sentence.text,
            )
            for task in tasks
        ),
        conflicts=(),
        retry_attempts=(
            sentence_context_selection.SelectionRetryAttempt(
                attempt=1,
                task_ids=(tasks[0].id,),
                reason="unknown_context_sentence_id",
            ),
        ),
    )

    validation = sentence_context_selection.validate_existing_report(report, tasks)

    assert validation.is_reusable is True
    assert validation.reason == "complete"


def test_validate_existing_report_rejects_incomplete_or_invalid_report() -> None:
    tasks = _tasks()
    missing_selection_report = sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            sentence_context_selection.SentenceContextSelection(
                task_id=tasks[0].id,
                selected_context_sentence_ids=(),
                original=tasks[0].main_sentence.text,
            ),
        ),
        conflicts=(),
    )
    invalid_report = sentence_context_selection.SentenceContextSelectionReport(
        selections=tuple(
            sentence_context_selection.SentenceContextSelection(
                task_id=task.id,
                selected_context_sentence_ids=(),
                original=task.main_sentence.text,
            )
            for task in tasks
        ),
        conflicts=(),
        invalid_context_selections=(
            sentence_context_selection.InvalidContextSelection(
                task_id=tasks[0].id,
                sentence_id="s99",
                reason="unknown_context_sentence_id",
            ),
        ),
    )

    missing_validation = sentence_context_selection.validate_existing_report(missing_selection_report, tasks)
    invalid_validation = sentence_context_selection.validate_existing_report(invalid_report, tasks)

    assert missing_validation.is_reusable is False
    assert missing_validation.reason == "missing_task_selections"
    assert invalid_validation.is_reusable is False
    assert invalid_validation.reason == "invalid_context_selections_present"


def _tasks() -> tuple[normative_audit.SentenceSelectionTask, ...]:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. This avoids ambiguous client behavior. New fields should explicitly set either `+optional` or `+required`.
""".strip()
    return normative_audit.extract_sentence_selection_tasks(document)
