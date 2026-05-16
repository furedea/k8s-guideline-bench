"""CLI entry point for Stage 1 constraint extraction tools.

Subcommands:
    review-sheet      Generate atomic constraint review sheet CSV.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import normative_audit  # noqa: E402
import sentence_context_selection  # noqa: E402

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
    _configure_sentence_context_selection_parser(
        subparsers.add_parser(
            "sentence-context-selection",
            help="Select source context sentences for generated sentence selection tasks.",
        ),
    )
    arguments = parser.parse_args()
    arguments.func(arguments)


def _configure_review_sheet_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--norms-path", type=Path, default=None)
    _ = parser.add_argument("--conventions-path", type=Path, default=None)
    _ = parser.add_argument("--interpretations-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    parser.set_defaults(func=_run_review_sheet)


def _configure_sentence_selection_tasks_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--conventions-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    _ = parser.add_argument("--audit-output-path", type=Path, default=None)
    parser.set_defaults(func=_run_sentence_selection_tasks)


def _configure_sentence_context_selection_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--tasks-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    _ = parser.add_argument("--codex-command", type=str, default="codex")
    _ = parser.add_argument("--model", type=str, default=None)
    _ = parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.set_defaults(func=_run_sentence_context_selection)


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
    audit_output_path = arguments.audit_output_path or (
        docs_dir / "mechanical" / "api-conventions" / "sentence_selection_audit.json"
    )

    artifacts = normative_audit.extract_sentence_selection_artifacts(conventions_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_output_path.parent.mkdir(parents=True, exist_ok=True)
    normative_audit.save_sentence_selection_tasks(artifacts.tasks, output_path)
    normative_audit.save_sentence_selection_audit(artifacts.audit_records, audit_output_path)

    print(f"Written {len(artifacts.tasks)} tasks to {output_path}")
    print(f"Written {len(artifacts.audit_records)} audit records to {audit_output_path}")


def _run_sentence_context_selection(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    docs_dir = project_root / "docs"
    tasks_path = arguments.tasks_path or (
        docs_dir / "mechanical" / "api-conventions" / "sentence_selection_tasks.json"
    )
    output_path = arguments.output_path or (docs_dir / "llm" / "api-conventions" / "sentence_context_selection.json")
    print(f"[sentence-context-selection] loading tasks from {tasks_path}", flush=True)
    tasks = sentence_context_selection.load_sentence_selection_tasks(tasks_path)
    print(
        f"[sentence-context-selection] running codex for {len(tasks)} tasks "
        f"(model={arguments.model or 'codex default'}, timeout={arguments.timeout_seconds}s)",
        flush=True,
    )
    report = sentence_context_selection.select_sentence_contexts_with_codex(
        tasks,
        codex_command=arguments.codex_command,
        model=arguments.model,
        timeout_seconds=arguments.timeout_seconds,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[sentence-context-selection] writing report to {output_path}", flush=True)
    sentence_context_selection.save_context_selection_report(report, output_path)
    print(f"[sentence-context-selection] selections={len(report.selections)}")
    print(f"[sentence-context-selection] conflicts={len(report.conflicts)}")


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
