import argparse
import json
from pathlib import Path

import main
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture


def test_main_without_subcommand_runs_default_constraint_pipeline(mocker: MockerFixture) -> None:
    calls: list[str] = []
    sentence_selection = mocker.patch(
        "main._run_sentence_selection_tasks",
        side_effect=lambda _: calls.append("sentence-selection-tasks"),
    )
    sentence_context_selection = mocker.patch(
        "main._run_sentence_context_selection",
        side_effect=lambda _: calls.append("sentence-context-selection"),
    )
    sentence_constraint_candidates = mocker.patch(
        "main._run_sentence_constraint_candidates",
        side_effect=lambda _: calls.append("sentence-constraint-candidates"),
    )
    sentence_interpretations = mocker.patch(
        "main._run_sentence_interpretations",
        side_effect=lambda _: calls.append("sentence-interpretations"),
    )
    review_sheet = mocker.patch("main._run_review_sheet", side_effect=lambda _: calls.append("review-sheet"))

    main.main(())

    assert calls == [
        "sentence-selection-tasks",
        "sentence-context-selection",
        "sentence-constraint-candidates",
        "sentence-interpretations",
        "review-sheet",
    ]
    sentence_selection.assert_called_once()
    assert sentence_selection.call_args.args[0].conventions_path is None
    assert sentence_selection.call_args.args[0].output_path is None
    assert sentence_selection.call_args.args[0].audit_output_path is None
    sentence_context_selection.assert_called_once()
    assert sentence_context_selection.call_args.args[0].tasks_path is None
    assert sentence_context_selection.call_args.args[0].output_path is None
    assert sentence_context_selection.call_args.args[0].codex_command == "codex"
    assert sentence_context_selection.call_args.args[0].model is None
    assert sentence_context_selection.call_args.args[0].timeout_seconds == 1800
    assert sentence_context_selection.call_args.args[0].max_retries == 3
    assert sentence_context_selection.call_args.args[0].batch_size == 25
    assert sentence_context_selection.call_args.args[0].stream_codex_output is False
    sentence_constraint_candidates.assert_called_once()
    assert sentence_constraint_candidates.call_args.args[0].tasks_path is None
    assert sentence_constraint_candidates.call_args.args[0].context_selection_path is None
    assert sentence_constraint_candidates.call_args.args[0].output_path is None
    assert sentence_constraint_candidates.call_args.args[0].codex_command == "codex"
    assert sentence_constraint_candidates.call_args.args[0].model is None
    assert sentence_constraint_candidates.call_args.args[0].timeout_seconds == 1800
    assert sentence_constraint_candidates.call_args.args[0].max_retries == 3
    assert sentence_constraint_candidates.call_args.args[0].batch_size == 25
    assert sentence_constraint_candidates.call_args.args[0].stream_codex_output is False
    sentence_interpretations.assert_called_once()
    assert sentence_interpretations.call_args.args[0].tasks_path is None
    assert sentence_interpretations.call_args.args[0].context_selection_path is None
    assert sentence_interpretations.call_args.args[0].output_path is None
    assert sentence_interpretations.call_args.args[0].codex_command == "codex"
    assert sentence_interpretations.call_args.args[0].model is None
    assert sentence_interpretations.call_args.args[0].timeout_seconds == 1800
    assert sentence_interpretations.call_args.args[0].max_retries == 3
    assert sentence_interpretations.call_args.args[0].batch_size == 25
    assert sentence_interpretations.call_args.args[0].stream_codex_output is False
    review_sheet.assert_called_once()
    assert review_sheet.call_args.args[0].norms_path is None
    assert review_sheet.call_args.args[0].conventions_path is None
    assert review_sheet.call_args.args[0].interpretations_path is None
    assert review_sheet.call_args.args[0].output_path is None


def test_run_sentence_selection_tasks_writes_json_from_source_markdown(tmp_path: Path) -> None:
    conventions_path = tmp_path / "api-conventions.md"
    conventions_path.write_text(
        """
## Section

Objects may report multiple conditions. This collection should be treated as a map with a key of `type`.
""".strip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "tasks.json"
    audit_output_path = tmp_path / "audit.json"

    main._run_sentence_selection_tasks(
        argparse.Namespace(
            conventions_path=conventions_path,
            output_path=output_path,
            audit_output_path=audit_output_path,
        ),
    )

    assert '"main_sentence": {' in output_path.read_text(encoding="utf-8")
    assert '"excluded": 1' in audit_output_path.read_text(encoding="utf-8")


def test_run_sentence_context_selection_writes_llm_selected_originals(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: CaptureFixture[str],
) -> None:
    tasks_path = tmp_path / "tasks.json"
    output_path = tmp_path / "selection.json"
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required.
""".strip()
    tasks = main.normative_audit.extract_sentence_selection_tasks(document)
    tasks_path.write_text(
        json.dumps({"tasks": [task.model_dump(mode="json") for task in tasks]}),
        encoding="utf-8",
    )
    select_contexts = mocker.patch(
        "main.sentence_context_selection.select_sentence_contexts_with_codex",
        return_value=main.sentence_context_selection.SentenceContextSelectionReport(
            selections=(
                main.sentence_context_selection.SentenceContextSelection(
                    task_id=tasks[0].id,
                    selected_context_sentence_ids=("s1",),
                    original="Optionality affects API compatibility. Fields must be either optional or required.",
                ),
            ),
            conflicts=(),
        ),
    )

    main._run_sentence_context_selection(
        argparse.Namespace(
            tasks_path=tasks_path,
            output_path=output_path,
            codex_command="codex",
            model="gpt-5.2",
            timeout_seconds=120,
            max_retries=2,
            batch_size=10,
            stream_codex_output=True,
        ),
    )

    select_contexts.assert_called_once()
    assert select_contexts.call_args.kwargs["codex_command"] == "codex"
    assert select_contexts.call_args.kwargs["model"] == "gpt-5.2"
    assert select_contexts.call_args.kwargs["timeout_seconds"] == 120
    assert select_contexts.call_args.kwargs["max_retries"] == 2
    assert select_contexts.call_args.kwargs["batch_size"] == 10
    assert select_contexts.call_args.kwargs["stream_output"] is True
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["selections"][0]["original"] == (
        "Optionality affects API compatibility. Fields must be either optional or required."
    )
    output = capsys.readouterr().out
    assert "[sentence-context-selection] loading tasks from" in output
    assert (
        "[sentence-context-selection] running codex for 1 tasks "
        "(model=gpt-5.2, timeout=120s, max_retries=2, batch_size=10, stream_codex_output=True)" in output
    )
    assert "[sentence-context-selection] writing report to" in output
    assert "[sentence-context-selection] selections=1" in output
    assert "[sentence-context-selection] conflicts=0" in output
    assert "[sentence-context-selection] invalid_context_selections=0" in output
    assert "[sentence-context-selection] retry_attempts=0" in output


def test_run_sentence_constraint_candidates_writes_llm_candidates(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: CaptureFixture[str],
) -> None:
    tasks_path = tmp_path / "tasks.json"
    context_selection_path = tmp_path / "context-selection.json"
    output_path = tmp_path / "constraint-candidates.json"
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required.
""".strip()
    tasks = main.normative_audit.extract_sentence_selection_tasks(document)
    tasks_path.write_text(
        json.dumps({"tasks": [task.model_dump(mode="json") for task in tasks]}),
        encoding="utf-8",
    )
    context_report = main.sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            main.sentence_context_selection.SentenceContextSelection(
                task_id=tasks[0].id,
                selected_context_sentence_ids=("s1",),
                original="Optionality affects API compatibility. Fields must be either optional or required.",
            ),
        ),
        conflicts=(),
    )
    main.sentence_context_selection.save_context_selection_report(context_report, context_selection_path)
    select_candidates = mocker.patch(
        "main.sentence_constraint_candidate.select_constraint_candidates_with_codex",
        return_value=main.sentence_constraint_candidate.SentenceConstraintCandidateReport(
            candidates=(
                main.sentence_constraint_candidate.SentenceConstraintCandidate(
                    id=f"{tasks[0].id}_c1",
                    task_id=tasks[0].id,
                    source_span=tasks[0].source_span,
                    source_strength=("obligation",),
                    original="Optionality affects API compatibility. Fields must be either optional or required.",
                    constraint="Fields must be either optional or required.",
                ),
            ),
        ),
    )

    main._run_sentence_constraint_candidates(
        argparse.Namespace(
            tasks_path=tasks_path,
            context_selection_path=context_selection_path,
            output_path=output_path,
            codex_command="codex",
            model="gpt-5.2",
            timeout_seconds=120,
            max_retries=2,
            batch_size=10,
            stream_codex_output=True,
        ),
    )

    select_candidates.assert_called_once()
    assert select_candidates.call_args.kwargs["codex_command"] == "codex"
    assert select_candidates.call_args.kwargs["model"] == "gpt-5.2"
    assert select_candidates.call_args.kwargs["timeout_seconds"] == 120
    assert select_candidates.call_args.kwargs["max_retries"] == 2
    assert select_candidates.call_args.kwargs["batch_size"] == 10
    assert select_candidates.call_args.kwargs["stream_output"] is True
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["candidates"][0]["constraint"] == "Fields must be either optional or required."
    output = capsys.readouterr().out
    assert "[sentence-constraint-candidates] loading tasks from" in output
    assert "[sentence-constraint-candidates] loading context selections from" in output
    assert (
        "[sentence-constraint-candidates] running codex for 1 tasks "
        "(model=gpt-5.2, timeout=120s, max_retries=2, batch_size=10, stream_codex_output=True)" in output
    )
    assert "[sentence-constraint-candidates] writing report to" in output
    assert "[sentence-constraint-candidates] candidates=1" in output
    assert "[sentence-constraint-candidates] retry_attempts=0" in output


def test_run_sentence_interpretations_writes_llm_interpretations(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: CaptureFixture[str],
) -> None:
    tasks_path = tmp_path / "tasks.json"
    context_selection_path = tmp_path / "context-selection.json"
    output_path = tmp_path / "interpretations.json"
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required.
""".strip()
    tasks = main.normative_audit.extract_sentence_selection_tasks(document)
    tasks_path.write_text(
        json.dumps({"tasks": [task.model_dump(mode="json") for task in tasks]}),
        encoding="utf-8",
    )
    context_report = main.sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            main.sentence_context_selection.SentenceContextSelection(
                task_id=tasks[0].id,
                selected_context_sentence_ids=("s1",),
                original="Optionality affects API compatibility. Fields must be either optional or required.",
            ),
        ),
        conflicts=(),
    )
    main.sentence_context_selection.save_context_selection_report(context_report, context_selection_path)
    select_interpretations = mocker.patch(
        "main.sentence_interpretation.select_interpretations_with_codex",
        return_value=main.sentence_interpretation.SentenceInterpretationReport(
            interpretations=(
                main.sentence_interpretation.SentenceInterpretation(
                    task_id=tasks[0].id,
                    source_span=tasks[0].source_span,
                    source_strength=("obligation",),
                    original="Optionality affects API compatibility. Fields must be either optional or required.",
                    interpretation="Fields must be either optional or required.",
                ),
            ),
        ),
    )

    main._run_sentence_interpretations(
        argparse.Namespace(
            tasks_path=tasks_path,
            context_selection_path=context_selection_path,
            output_path=output_path,
            codex_command="codex",
            model="gpt-5.2",
            timeout_seconds=120,
            max_retries=2,
            batch_size=10,
            stream_codex_output=True,
        ),
    )

    select_interpretations.assert_called_once()
    assert select_interpretations.call_args.kwargs["codex_command"] == "codex"
    assert select_interpretations.call_args.kwargs["model"] == "gpt-5.2"
    assert select_interpretations.call_args.kwargs["timeout_seconds"] == 120
    assert select_interpretations.call_args.kwargs["max_retries"] == 2
    assert select_interpretations.call_args.kwargs["batch_size"] == 10
    assert select_interpretations.call_args.kwargs["stream_output"] is True
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["interpretations"][0]["interpretation"] == ("Fields must be either optional or required.")
    output = capsys.readouterr().out
    assert "[sentence-interpretations] loading tasks from" in output
    assert "[sentence-interpretations] loading context selections from" in output
    assert (
        "[sentence-interpretations] running codex for 1 tasks "
        "(model=gpt-5.2, timeout=120s, max_retries=2, batch_size=10, stream_codex_output=True)" in output
    )
    assert "[sentence-interpretations] writing report to" in output
    assert "[sentence-interpretations] interpretations=1" in output
    assert "[sentence-interpretations] retry_attempts=0" in output


def test_run_sentence_context_selection_skips_reusable_existing_report(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: CaptureFixture[str],
) -> None:
    tasks_path = tmp_path / "tasks.json"
    output_path = tmp_path / "selection.json"
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required.
""".strip()
    tasks = main.normative_audit.extract_sentence_selection_tasks(document)
    tasks_path.write_text(
        json.dumps({"tasks": [task.model_dump(mode="json") for task in tasks]}),
        encoding="utf-8",
    )
    existing_report = main.sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            main.sentence_context_selection.SentenceContextSelection(
                task_id=tasks[0].id,
                selected_context_sentence_ids=("s1",),
                original="Optionality affects API compatibility. Fields must be either optional or required.",
            ),
        ),
        conflicts=(),
    )
    main.sentence_context_selection.save_context_selection_report(existing_report, output_path)
    select_contexts = mocker.patch("main.sentence_context_selection.select_sentence_contexts_with_codex")

    main._run_sentence_context_selection(
        argparse.Namespace(
            tasks_path=tasks_path,
            output_path=output_path,
            codex_command="codex",
            model=None,
            timeout_seconds=120,
            max_retries=2,
            batch_size=25,
            stream_codex_output=False,
        ),
    )

    select_contexts.assert_not_called()
    output = capsys.readouterr().out
    assert "[sentence-context-selection] skip existing report:" in output
    assert "[sentence-context-selection] selections=1" in output
