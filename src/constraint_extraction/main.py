"""CLI entry point for Stage 1 constraint extraction tools.

Subcommands:
    source-selection  Generate guideline source selection report.
    review-sheet      Generate atomic constraint review sheet CSV.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import normative_audit  # noqa: E402
import project_paths  # noqa: E402
import source_selection  # noqa: E402
import source_selection_config  # noqa: E402

REPO_PATH_ENV_VAR = "K8S_GUIDELINE_BENCH_REPO_PATH"

REVIEW_SHEET_FIELDNAMES = [
    "id",
    "source_span",
    "source_strength",
    "original",
    "text",
    "interpretation",
    "atomic",
    "beyond_syntax",
    "diff_code_related",
    "objective",
    "grounded",
    "decision",
    "notes",
]


def main() -> None:
    """Dispatch to the selected subcommand."""
    parser = argparse.ArgumentParser(description="Stage 1: constraint extraction tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _configure_source_selection_parser(
        subparsers.add_parser(
            "source-selection",
            help="Generate guideline source selection report from Kubernetes history.",
        ),
    )
    _configure_review_sheet_parser(
        subparsers.add_parser(
            "review-sheet",
            help="Generate atomic constraint review sheet CSV from normative constraints.",
        ),
    )
    _configure_sentence_selection_tasks_parser(
        subparsers.add_parser(
            "sentence-selection-tasks",
            help="Generate sentence selection task JSON for one-shot LLM normalization.",
        ),
    )
    arguments = parser.parse_args()
    arguments.func(arguments)


def _configure_source_selection_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--config", type=Path, default=None)
    _ = parser.add_argument("--repo-path", type=Path, default=None)
    _ = parser.add_argument("--since", type=str, default=None)
    _ = parser.add_argument("--grep", type=str, default=None)
    _ = parser.add_argument("--minimum-match-count", type=int, default=None)
    _ = parser.add_argument("--markdown-report-path", type=Path, default=None)
    _ = parser.add_argument("--json-report-path", type=Path, default=None)
    parser.set_defaults(func=_run_source_selection)


def _configure_review_sheet_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--norms-path", type=Path, default=None)
    _ = parser.add_argument("--conventions-path", type=Path, default=None)
    _ = parser.add_argument("--interpretations-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    parser.set_defaults(func=_run_review_sheet)


def _configure_sentence_selection_tasks_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--conventions-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    parser.set_defaults(func=_run_sentence_selection_tasks)


def _run_source_selection(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    paths = project_paths.ProjectPaths.from_root(project_root)
    config_path = arguments.config or (paths.config_directory / "source_selection.json")
    config = source_selection_config.load_source_selection_config(config_path)

    repo_path = _resolve_repo_path(paths.root, arguments.repo_path, config.repo_path)
    since = arguments.since or config.since
    grep = arguments.grep or config.grep
    minimum_match_count = arguments.minimum_match_count or config.minimum_match_count
    markdown_report_path = _resolve_output_path(
        paths.root,
        arguments.markdown_report_path or config.markdown_report_path,
    )
    json_report_path = _resolve_output_path(
        paths.root,
        arguments.json_report_path or config.json_report_path,
    )
    sources = _resolve_source_paths(repo_path, config.sources)

    markdown_report_path.parent.mkdir(parents=True, exist_ok=True)
    json_report_path.parent.mkdir(parents=True, exist_ok=True)

    commits = source_selection.collect_refactor_commits(
        repo_path=repo_path,
        target_paths=config.target_paths,
        since=since,
        grep=grep,
    )
    coverage = source_selection.select_guideline_sources(
        sources=sources,
        commits=commits,
        minimum_match_count=minimum_match_count,
    )

    markdown_report = source_selection.render_selection_markdown(coverage, repo_path)
    _ = markdown_report_path.write_text(markdown_report, encoding="utf-8")
    source_selection.save_selection_report(json_report_path, coverage, repo_path)


def _run_review_sheet(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    docs_dir = project_root / "docs"
    norms_path = arguments.norms_path or (docs_dir / "llm" / "api-conventions" / "normative_constraints.json")
    conventions_path = arguments.conventions_path or (docs_dir / "source" / "api-conventions.md")
    interpretations_path = arguments.interpretations_path or (
        docs_dir / "llm" / "api-conventions" / "normative_interpretations.json"
    )
    output_path = arguments.output_path or (
        docs_dir / "human" / "api-conventions" / "atomic_constraint_review_sheet.csv"
    )

    norms = _load_norms(norms_path)
    lines = _load_lines(conventions_path)
    interpretations = _load_interpretations(interpretations_path)
    rows = [_build_row(norm, lines, interpretations) for norm in norms]
    _write_csv(rows, output_path)

    filled = sum(1 for row in rows if row["interpretation"])
    print(f"Written {len(rows)} rows to {output_path}")
    print(f"Interpretations: {filled}/{len(rows)}")


def _run_sentence_selection_tasks(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    docs_dir = project_root / "docs"
    conventions_path = arguments.conventions_path or (docs_dir / "source" / "api-conventions.md")
    output_path = arguments.output_path or (
        docs_dir / "mechanical" / "api-conventions" / "sentence_selection_tasks.json"
    )

    tasks = normative_audit.extract_sentence_selection_tasks(conventions_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normative_audit.save_sentence_selection_tasks(tasks, output_path)

    print(f"Written {len(tasks)} tasks to {output_path}")


def _resolve_repo_path(
    project_root: Path,
    cli_repo_path: Path | None,
    config_repo_path: Path | None,
) -> Path:
    """Resolve the external Kubernetes repository path."""
    if cli_repo_path is not None:
        return cli_repo_path if cli_repo_path.is_absolute() else project_root / cli_repo_path
    env_repo_path = os.getenv(REPO_PATH_ENV_VAR)
    if env_repo_path:
        env_path = Path(env_repo_path)
        return env_path if env_path.is_absolute() else project_root / env_path
    if config_repo_path is not None:
        return config_repo_path if config_repo_path.is_absolute() else project_root / config_repo_path
    raise ValueError(
        f"Kubernetes repository path is required. Pass --repo-path, set {REPO_PATH_ENV_VAR},"
        " or define repo_path in the config.",
    )


def _resolve_output_path(project_root: Path, configured_path: Path) -> Path:
    """Resolve an output path relative to the project root when needed."""
    if configured_path.is_absolute():
        return configured_path
    return project_root / configured_path


def _resolve_source_paths(
    repo_path: Path,
    sources: tuple[source_selection.GuidelineSource, ...],
) -> tuple[source_selection.GuidelineSource, ...]:
    """Resolve source document paths relative to the Kubernetes repo root."""
    resolved_sources: list[source_selection.GuidelineSource] = []
    for source in sources:
        resolved_path = source.path if source.path.is_absolute() else repo_path / source.path
        resolved_sources.append(source.model_copy(update={"path": resolved_path}))
    return tuple(resolved_sources)


def _load_norms(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["constraints"]


def _load_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _load_interpretations(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return json.loads(raw)


def _extract_original(lines: list[str], span: str) -> str:
    """Extract original text from api-conventions.md by line span."""
    start_s, end_s = span.split("-")
    start, end = int(start_s), int(end_s)
    return " ".join(line.strip() for line in lines[start - 1 : end] if line.strip())


def _build_row(
    norm: dict[str, Any],
    lines: list[str],
    interpretations: dict[str, str],
) -> dict[str, str]:
    norm_id = norm["id"]
    return {
        "id": norm_id,
        "source_span": norm["source_span"],
        "source_strength": norm["strength_signal"],
        "original": _extract_original(lines, norm["source_span"]),
        "text": norm["text"],
        "interpretation": interpretations.get(norm_id, ""),
        "atomic": "",
        "beyond_syntax": "",
        "diff_code_related": "",
        "objective": "",
        "grounded": "",
        "decision": "",
        "notes": "",
    }


def _write_csv(rows: list[dict[str, str]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_SHEET_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
