import argparse
from pathlib import Path

import main


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
