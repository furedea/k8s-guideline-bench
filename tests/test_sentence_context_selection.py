import json
from pathlib import Path

import normative_audit
import sentence_context_selection


class FakeCompletionClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        self.calls.append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
        return self.response


def test_select_sentence_contexts_materializes_original_and_detects_conflicts() -> None:
    tasks = _tasks()
    client = FakeCompletionClient(
        json.dumps(
            {
                "selections": [
                    {"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1", "s3"]},
                    {"task_id": tasks[1].id, "selected_context_sentence_ids": ["s1", "s3"]},
                ],
            },
        ),
    )

    report = sentence_context_selection.select_sentence_contexts(
        tasks,
        client=client,
        model="claude-sonnet-4-6",
        max_tokens=1024,
    )

    assert client.calls[0]["model"] == "claude-sonnet-4-6"
    assert client.calls[0]["max_tokens"] == 1024
    assert "Return JSON only" in str(client.calls[0]["user"])
    assert report.selections[0].original == (
        "Optionality affects API compatibility. "
        "Fields must be either optional or required. "
        "This avoids ambiguous client behavior."
    )
    assert report.conflicts[0].sentence_id == "s3"
    assert report.conflicts[0].task_ids == (tasks[0].id, tasks[1].id)


def test_select_sentence_contexts_rejects_missing_task_selection() -> None:
    tasks = _tasks()
    client = FakeCompletionClient(
        json.dumps(
            {
                "selections": [
                    {"task_id": tasks[0].id, "selected_context_sentence_ids": []},
                ],
            },
        ),
    )

    try:
        _ = sentence_context_selection.select_sentence_contexts(
            tasks,
            client=client,
            model="claude-sonnet-4-6",
            max_tokens=1024,
        )
    except ValueError as exc:
        assert "missing=" in str(exc)
    else:
        raise AssertionError("Expected missing task selection to fail")


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


def _tasks() -> tuple[normative_audit.SentenceSelectionTask, ...]:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. This avoids ambiguous client behavior. New fields should explicitly set either `+optional` or `+required`.
""".strip()
    return normative_audit.extract_sentence_selection_tasks(document)
