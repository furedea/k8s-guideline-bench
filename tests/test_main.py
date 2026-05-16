import argparse
from pathlib import Path

import main
import pytest
import source_selection
from pytest_mock import MockerFixture


def test_resolve_output_path_uses_project_root_for_relative_path() -> None:
    project_root = Path("/tmp/project")

    resolved = main._resolve_output_path(project_root, Path("results/report.md"))

    assert resolved == Path("/tmp/project/results/report.md")


def test_resolve_source_paths_joins_repo_root_for_relative_source_paths() -> None:
    repo_root = Path("/tmp/kubernetes")
    source = source_selection.GuidelineSource(
        id="api_rules",
        title="API rules",
        path=Path("api/api-rules/README.md"),
        summary="API rules",
        keyword_patterns=(r"\bapi\b",),
        rationale="API conventions",
    )

    resolved_sources = main._resolve_source_paths(repo_root, (source,))

    assert resolved_sources[0].path == Path("/tmp/kubernetes/api/api-rules/README.md")


def test_resolve_repo_path_joins_project_root_for_relative_config_path() -> None:
    resolved = main._resolve_repo_path(
        Path("/tmp/project"),
        None,
        Path("kubernetes"),
    )

    assert resolved == Path("/tmp/project/kubernetes")


def test_resolve_repo_path_requires_explicit_input(mocker: MockerFixture) -> None:
    mocker.patch("main.os.getenv", return_value=None)

    with pytest.raises(ValueError):
        _ = main._resolve_repo_path(Path("/tmp/project"), None, None)


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
