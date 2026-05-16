import argparse
import json
from pathlib import Path

import main
from pytest_mock import MockerFixture


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


def test_run_sentence_context_selection_writes_llm_selected_originals(tmp_path: Path, mocker: MockerFixture) -> None:
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
    fake_client = mocker.Mock()
    fake_client.complete.return_value = json.dumps(
        {"selections": [{"task_id": tasks[0].id, "selected_context_sentence_ids": ["s1"]}]},
    )
    build_client = mocker.patch("main.completion_client_factory.build_completion_client", return_value=fake_client)

    main._run_sentence_context_selection(
        argparse.Namespace(
            tasks_path=tasks_path,
            output_path=output_path,
            client_type="claude_cli",
            api_key_env=None,
            base_url=None,
            command="claude",
            model="claude-sonnet-4-6",
            max_tokens=2048,
        ),
    )

    build_client.assert_called_once()
    fake_client.complete.assert_called_once()
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["selections"][0]["original"] == (
        "Optionality affects API compatibility. Fields must be either optional or required."
    )
