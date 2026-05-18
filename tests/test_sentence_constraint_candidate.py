import json
import subprocess
from pathlib import Path

import normative_audit
import sentence_constraint_candidate
import sentence_context_selection
from pytest_mock import MockerFixture


def test_build_constraint_candidate_tasks_joins_sentence_tasks_with_selected_originals() -> None:
    sentence_tasks = _sentence_tasks()
    context_report = sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            sentence_context_selection.SentenceContextSelection(
                task_id=sentence_tasks[0].id,
                selected_context_sentence_ids=("s1",),
                original="Optionality affects API compatibility. Fields must be either optional or required.",
            ),
            sentence_context_selection.SentenceContextSelection(
                task_id=sentence_tasks[1].id,
                selected_context_sentence_ids=(),
                original="New fields should explicitly set either `+optional` or `+required`.",
            ),
        ),
        conflicts=(),
    )

    tasks = sentence_constraint_candidate.build_constraint_candidate_tasks(sentence_tasks, context_report)

    assert tasks[0].id == sentence_tasks[0].id
    assert tasks[0].source_span == sentence_tasks[0].source_span
    assert tasks[0].source_strength == ("obligation",)
    assert tasks[0].original == ("Optionality affects API compatibility. Fields must be either optional or required.")
    assert tasks[0].reference_context == ()


def test_build_constraint_candidate_tasks_adds_reference_context_only_for_demonstrative_originals() -> None:
    sentence_tasks = (
        _sentence_task(
            task_id="block_0001_s1",
            block_id="block_0001",
            block_original="kind: a string that identifies the schema this object should have",
            main_sentence_text="kind: a string that identifies the schema this object should have",
        ),
        _sentence_task(
            task_id="block_0002_s1",
            block_id="block_0002",
            block_original="apiVersion: a string that identifies the version of the schema the object should have",
            main_sentence_text="apiVersion: a string that identifies the version of the schema the object should have",
        ),
        _sentence_task(
            task_id="block_0003_s1",
            block_id="block_0003",
            block_original="These fields are required for proper decoding of the object.",
            main_sentence_text="These fields are required for proper decoding of the object.",
        ),
    )
    context_report = sentence_context_selection.SentenceContextSelectionReport(
        selections=(
            sentence_context_selection.SentenceContextSelection(
                task_id="block_0001_s1",
                selected_context_sentence_ids=(),
                original="kind: a string that identifies the schema this object should have",
            ),
            sentence_context_selection.SentenceContextSelection(
                task_id="block_0002_s1",
                selected_context_sentence_ids=(),
                original="apiVersion: a string that identifies the version of the schema the object should have",
            ),
            sentence_context_selection.SentenceContextSelection(
                task_id="block_0003_s1",
                selected_context_sentence_ids=(),
                original="These fields are required for proper decoding of the object.",
            ),
        ),
        conflicts=(),
    )

    tasks = sentence_constraint_candidate.build_constraint_candidate_tasks(sentence_tasks, context_report)

    assert tasks[0].reference_context == ()
    assert tasks[1].reference_context == ()
    assert tasks[2].reference_context == (
        "Section: API conventions",
        "Previous block: kind: a string that identifies the schema this object should have",
        "Previous block: apiVersion: a string that identifies the version of the schema the object should have",
    )


def test_select_constraint_candidates_with_codex_writes_one_draft_per_original(mocker: MockerFixture) -> None:
    tasks = _candidate_tasks()
    codex_run = mocker.patch(
        "sentence_constraint_candidate.run_codex_constraint_candidates",
        side_effect=(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": tasks[0].id,
                            "constraint": "Fields must be either optional or required.",
                        },
                    ],
                },
            ),
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": tasks[1].id,
                            "constraint": "New fields should set optional or required tags.",
                        },
                    ],
                },
            ),
        ),
    )

    report = sentence_constraint_candidate.select_constraint_candidates_with_codex(
        tasks,
        codex_command="codex",
        model="gpt-5.2",
        timeout_seconds=120,
        batch_size=1,
    )

    assert codex_run.call_count == 2
    assert "Return JSON only" in codex_run.call_args_list[0].args[0]
    assert (
        "rewrite the original source text into exactly one reviewable draft constraint"
        in (codex_run.call_args_list[0].args[0])
    )
    assert "Preserve the normative meaning" in codex_run.call_args_list[0].args[0]
    assert "reference_context" in codex_run.call_args_list[0].args[0]
    assert codex_run.call_args_list[0].kwargs["model"] == "gpt-5.2"
    assert tuple(candidate.id for candidate in report.candidates) == (
        tasks[0].id,
        tasks[1].id,
    )
    assert report.candidates[0].constraint == "Fields must be either optional or required."
    assert report.retry_attempts == ()


def test_select_constraint_candidates_with_codex_retries_missing_task_candidates(mocker: MockerFixture) -> None:
    tasks = _candidate_tasks()
    mocker.patch(
        "sentence_constraint_candidate.run_codex_constraint_candidates",
        side_effect=(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": tasks[0].id,
                            "constraint": "A",
                        },
                    ],
                },
            ),
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": tasks[1].id,
                            "constraint": "B",
                        },
                    ],
                },
            ),
        ),
    )

    report = sentence_constraint_candidate.select_constraint_candidates_with_codex(tasks, max_retries=1)

    assert tuple(candidate.task_id for candidate in report.candidates) == (tasks[0].id, tasks[1].id)
    assert report.retry_attempts[0].reason == "missing_task_constraints"
    assert report.retry_attempts[0].task_ids == (tasks[1].id,)


def test_select_constraint_candidates_with_codex_normalizes_ascii_sentence_punctuation(
    mocker: MockerFixture,
) -> None:
    tasks = _candidate_tasks()[:1]
    mocker.patch(
        "sentence_constraint_candidate.run_codex_constraint_candidates",
        return_value=json.dumps(
            {
                "tasks": [
                    {
                        "task_id": tasks[0].id,
                        "constraint": (
                            "Fields must be either optional or required\uff0cand this schema must be stable\uff0e"
                        ),
                    },
                ],
            },
        ),
    )

    report = sentence_constraint_candidate.select_constraint_candidates_with_codex(tasks)

    assert report.candidates[0].constraint == (
        "Fields must be either optional or required, and this schema must be stable."
    )


def test_run_codex_constraint_candidates_uses_schema_and_last_message(mocker: MockerFixture) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text('{"tasks":[]}', encoding="utf-8")
        assert command[:2] == ["codex", "exec"]
        assert "--output-schema" in command
        assert command[-1] == "-"
        assert kwargs["input"] == "prompt"
        assert kwargs["timeout"] == 30
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    run = mocker.patch("sentence_constraint_candidate.subprocess.run", side_effect=fake_run)

    response = sentence_constraint_candidate.run_codex_constraint_candidates(
        "prompt",
        codex_command="codex",
        model="gpt-5.2",
        timeout_seconds=30,
    )

    assert response == '{"tasks":[]}'
    assert "--model" in run.call_args.args[0]


def test_load_and_save_constraint_candidate_report(tmp_path: Path) -> None:
    output_path = tmp_path / "constraint-candidates.json"
    report = sentence_constraint_candidate.SentenceConstraintCandidateReport(
        candidates=(
            sentence_constraint_candidate.SentenceConstraintCandidate(
                id="block_0001_s1",
                task_id="block_0001_s1",
                source_span="10-10",
                source_strength=("obligation",),
                original="Fields must be either optional or required.",
                constraint="Fields must be either optional or required.",
            ),
        ),
    )

    sentence_constraint_candidate.save_constraint_candidate_report(report, output_path)
    loaded = sentence_constraint_candidate.load_constraint_candidate_report(output_path)

    assert loaded == report


def _sentence_tasks() -> tuple[normative_audit.SentenceSelectionTask, ...]:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. New fields should explicitly set either `+optional` or `+required`.
""".strip()
    return normative_audit.extract_sentence_selection_tasks(document)


def _candidate_tasks() -> tuple[sentence_constraint_candidate.SentenceConstraintCandidateTask, ...]:
    sentence_tasks = _sentence_tasks()
    return (
        sentence_constraint_candidate.SentenceConstraintCandidateTask(
            id=sentence_tasks[0].id,
            source_span=sentence_tasks[0].source_span,
            source_strength=("obligation",),
            original="Fields must be either optional or required.",
            reference_context=(),
        ),
        sentence_constraint_candidate.SentenceConstraintCandidateTask(
            id=sentence_tasks[1].id,
            source_span=sentence_tasks[1].source_span,
            source_strength=("recommendation",),
            original="New fields should explicitly set either `+optional` or `+required`.",
            reference_context=(),
        ),
    )


def _sentence_task(
    *,
    task_id: str,
    block_id: str,
    block_original: str,
    main_sentence_text: str,
) -> normative_audit.SentenceSelectionTask:
    return normative_audit.SentenceSelectionTask(
        id=task_id,
        block_id=block_id,
        source_span="1-1",
        section="API conventions",
        kind=normative_audit.CandidateKind.PARAGRAPH_SENTENCE,
        block_original=block_original,
        main_sentence=normative_audit.SourceSentence(
            id="s1",
            text=main_sentence_text,
            has_keyword=True,
            signal_tags=(normative_audit.SignalTag.OBLIGATION,),
        ),
        context_sentences=(),
    )
