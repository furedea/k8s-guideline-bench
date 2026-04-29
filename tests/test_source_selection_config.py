from pathlib import Path

import error
import pytest
import source_selection_config


def test_load_source_selection_config_reads_json_definition(tmp_path: Path) -> None:
    config_path = tmp_path / "source_selection.json"
    _ = config_path.write_text(
        """
{
  "repo_path": "/tmp/kubernetes",
  "target_paths": ["api", "pkg/apis"],
  "since": "12 months ago",
  "grep": "refactor|cleanup",
  "minimum_match_count": 2,
  "markdown_report_path": "/tmp/results/report.md",
  "json_report_path": "/tmp/results/report.json",
  "sources": [
    {
      "id": "api_rules",
      "title": "API rules",
      "path": "/tmp/api-rules/README.md",
      "summary": "Rules",
      "keyword_patterns": ["api"],
      "rationale": "API"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    config = source_selection_config.load_source_selection_config(config_path)

    assert config.repo_path == Path("/tmp/kubernetes")
    assert config.target_paths == ("api", "pkg/apis")
    assert config.minimum_match_count == 2
    assert config.sources[0].id == "api_rules"


def test_load_source_selection_config_allows_relative_repo_path(tmp_path: Path) -> None:
    config_path = tmp_path / "source_selection.json"
    _ = config_path.write_text(
        """
{
  "repo_path": "kubernetes",
  "target_paths": ["api"],
  "since": "12 months ago",
  "grep": "refactor",
  "minimum_match_count": 1,
  "markdown_report_path": "results/report.md",
  "json_report_path": "results/report.json",
  "sources": [
    {
      "id": "api_rules",
      "title": "API rules",
      "path": "api/api-rules/README.md",
      "summary": "Rules",
      "keyword_patterns": ["api"],
      "rationale": "API"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    config = source_selection_config.load_source_selection_config(config_path)

    assert config.repo_path == Path("kubernetes")


def test_load_source_selection_config_rejects_invalid_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "source_selection.json"
    _ = config_path.write_text("{}", encoding="utf-8")

    with pytest.raises(error.ConstraintCatalogError):
        _ = source_selection_config.load_source_selection_config(config_path)
