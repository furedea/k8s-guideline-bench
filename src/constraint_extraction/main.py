"""CLI entry point for Stage 1 constraint extraction tools.

Subcommands:
    normative-sentence-selection
                      Generate normative sentence selection JSON.
    sentence-context-selection
                      Select source context sentences with Codex.
    constraint-drafts
                      Generate draft constraints with Codex.
    constraint-interpretations
                      Generate draft constraint interpretations with Codex.
    kube-api-linter-hints
                      Generate kube-api-linter review hints.
    review-sheet      Generate atomic constraint review sheet CSV.
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import kube_api_linter_relation  # noqa: E402
import normative_audit  # noqa: E402
import sentence_constraint_candidate  # noqa: E402
import sentence_context_selection  # noqa: E402
import sentence_interpretation  # noqa: E402

CONSTRAINT_ARTIFACTS_DIR = Path("artifacts") / "constraint-extraction" / "api-conventions"

REVIEW_SHEET_FIELDNAMES = [
    "ID",
    "Source-Span",
    "Source_Strength",
    "Original",
    "Constraint",
    "Interpretation",
    "Kube-API-Linter",
    "Atomic",
    "Beyond-Syntax",
    "Diff-Closed",
    "Objective",
    "Grounded",
    "Decision(Auto)",
    "Notes",
]


def main(argv: tuple[str, ...] | None = None) -> None:
    """Dispatch to the selected subcommand."""
    parser = argparse.ArgumentParser(description="Stage 1: constraint extraction tools.")
    subparsers = parser.add_subparsers(dest="command")
    _configure_review_sheet_parser(
        subparsers.add_parser(
            "review-sheet",
            help="Generate atomic constraint review sheet CSV from normative constraints.",
        ),
    )
    _configure_normative_sentence_selection_parser(
        subparsers.add_parser(
            "normative-sentence-selection",
            help="Generate normative sentence selection JSON for one-shot LLM normalization.",
        ),
    )
    _configure_sentence_context_selection_parser(
        subparsers.add_parser(
            "sentence-context-selection",
            help="Select source context sentences for generated sentence selection tasks.",
        ),
    )
    _configure_constraint_drafts_parser(
        subparsers.add_parser(
            "constraint-drafts",
            help="Generate draft constraints from selected originals.",
        ),
    )
    _configure_constraint_interpretations_parser(
        subparsers.add_parser(
            "constraint-interpretations",
            help="Generate reviewer-facing interpretations for draft constraints.",
        ),
    )
    _configure_kube_api_linter_hints_parser(
        subparsers.add_parser(
            "kube-api-linter-hints",
            help="Generate kube-api-linter review hints for draft constraints.",
        ),
    )
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        _run_default_constraint_pipeline()
        return
    arguments.func(arguments)


def _run_default_constraint_pipeline() -> None:
    """Run the standard constraint extraction pipeline."""
    print("[constraint-extraction] running normative-sentence-selection", flush=True)
    _run_normative_sentence_selection(
        argparse.Namespace(
            conventions_path=None,
            output_path=None,
            audit_output_path=None,
        ),
    )
    print("[constraint-extraction] running sentence-context-selection", flush=True)
    _run_sentence_context_selection(
        argparse.Namespace(
            tasks_path=None,
            output_path=None,
            codex_command="codex",
            model=None,
            timeout_seconds=1800,
            max_retries=3,
            batch_size=25,
            stream_codex_output=False,
        ),
    )
    print("[constraint-extraction] running constraint-drafts", flush=True)
    _run_constraint_drafts(
        argparse.Namespace(
            tasks_path=None,
            context_selection_path=None,
            output_path=None,
            codex_command="codex",
            model=None,
            timeout_seconds=1800,
            max_retries=3,
            batch_size=25,
            stream_codex_output=False,
        ),
    )
    print("[constraint-extraction] running constraint-interpretations", flush=True)
    _run_constraint_interpretations(
        argparse.Namespace(
            constraint_drafts_path=None,
            output_path=None,
            codex_command="codex",
            model=None,
            timeout_seconds=1800,
            max_retries=3,
            batch_size=25,
            stream_codex_output=False,
        ),
    )
    print("[constraint-extraction] running kube-api-linter-hints", flush=True)
    _run_kube_api_linter_hints(
        argparse.Namespace(
            constraint_drafts_path=None,
            output_path=None,
        ),
    )
    print("[constraint-extraction] running review-sheet", flush=True)
    _run_review_sheet(
        argparse.Namespace(
            constraint_drafts_path=None,
            constraint_interpretations_path=None,
            kube_api_linter_hints_path=None,
            output_path=None,
        ),
    )


def _configure_review_sheet_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--constraint-drafts-path", type=Path, default=None)
    _ = parser.add_argument("--constraint-interpretations-path", type=Path, default=None)
    _ = parser.add_argument("--kube-api-linter-hints-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    parser.set_defaults(func=_run_review_sheet)


def _configure_normative_sentence_selection_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--conventions-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    _ = parser.add_argument("--audit-output-path", type=Path, default=None)
    parser.set_defaults(func=_run_normative_sentence_selection)


def _configure_sentence_context_selection_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--tasks-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    _ = parser.add_argument("--codex-command", type=str, default="codex")
    _ = parser.add_argument("--model", type=str, default=None)
    _ = parser.add_argument("--timeout-seconds", type=int, default=1800)
    _ = parser.add_argument("--max-retries", type=int, default=3)
    _ = parser.add_argument("--batch-size", type=int, default=25)
    _ = parser.add_argument("--stream-codex-output", action="store_true")
    parser.set_defaults(func=_run_sentence_context_selection)


def _configure_constraint_drafts_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--tasks-path", type=Path, default=None)
    _ = parser.add_argument("--context-selection-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    _ = parser.add_argument("--codex-command", type=str, default="codex")
    _ = parser.add_argument("--model", type=str, default=None)
    _ = parser.add_argument("--timeout-seconds", type=int, default=1800)
    _ = parser.add_argument("--max-retries", type=int, default=3)
    _ = parser.add_argument("--batch-size", type=int, default=25)
    _ = parser.add_argument("--stream-codex-output", action="store_true")
    parser.set_defaults(func=_run_constraint_drafts)


def _configure_constraint_interpretations_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--constraint-drafts-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    _ = parser.add_argument("--codex-command", type=str, default="codex")
    _ = parser.add_argument("--model", type=str, default=None)
    _ = parser.add_argument("--timeout-seconds", type=int, default=1800)
    _ = parser.add_argument("--max-retries", type=int, default=3)
    _ = parser.add_argument("--batch-size", type=int, default=25)
    _ = parser.add_argument("--stream-codex-output", action="store_true")
    parser.set_defaults(func=_run_constraint_interpretations)


def _configure_kube_api_linter_hints_parser(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--constraint-drafts-path", type=Path, default=None)
    _ = parser.add_argument("--output-path", type=Path, default=None)
    parser.set_defaults(func=_run_kube_api_linter_hints)


def _run_review_sheet(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    artifacts_dir = project_root / CONSTRAINT_ARTIFACTS_DIR
    constraint_drafts_path = arguments.constraint_drafts_path or (artifacts_dir / "llm" / "constraint_drafts.json")
    constraint_interpretations_path = arguments.constraint_interpretations_path or (
        artifacts_dir / "llm" / "constraint_interpretations.json"
    )
    kube_api_linter_hints_path = arguments.kube_api_linter_hints_path or (
        artifacts_dir / "llm" / "kube_api_linter_hints.json"
    )
    output_path = arguments.output_path or (artifacts_dir / "human" / "atomic_constraint_review_sheet.csv")

    print(f"[review-sheet] loading constraint drafts from {constraint_drafts_path}", flush=True)
    candidate_report = sentence_constraint_candidate.load_constraint_candidate_report(constraint_drafts_path)
    print(f"[review-sheet] loading constraint interpretations from {constraint_interpretations_path}", flush=True)
    interpretation_report = sentence_interpretation.load_interpretation_report(constraint_interpretations_path)
    interpretations = {
        interpretation.task_id: interpretation.interpretation
        for interpretation in interpretation_report.interpretations
    }
    print(f"[review-sheet] loading kube-api-linter hints from {kube_api_linter_hints_path}", flush=True)
    relation_report = kube_api_linter_relation.load_relation_report(kube_api_linter_hints_path)
    kube_api_linter_rules = {relation.task_id: relation.rules for relation in relation_report.relations}
    rows = [
        _build_review_row(
            candidate,
            interpretation=interpretations.get(candidate.task_id, ""),
            kube_api_linter_rules=kube_api_linter_rules.get(candidate.task_id, ()),
        )
        for candidate in candidate_report.candidates
    ]
    _write_csv(rows, output_path)

    filled = sum(1 for row in rows if row["Interpretation"])
    related = sum(1 for row in rows if row["Kube-API-Linter"])
    print(f"[review-sheet] written rows={len(rows)} to {output_path}")
    print(f"[review-sheet] interpretations={filled}/{len(rows)}")
    print(f"[review-sheet] kube_api_linter_hints={related}/{len(rows)}")


def _run_normative_sentence_selection(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    docs_dir = project_root / "docs"
    artifacts_dir = project_root / CONSTRAINT_ARTIFACTS_DIR
    conventions_path = arguments.conventions_path or (docs_dir / "source" / "api-conventions.md")
    output_path = arguments.output_path or (artifacts_dir / "mechanical" / "normative_sentence_selection.json")
    audit_output_path = arguments.audit_output_path or (
        artifacts_dir / "mechanical" / "normative_sentence_selection_audit.json"
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
    artifacts_dir = project_root / CONSTRAINT_ARTIFACTS_DIR
    tasks_path = arguments.tasks_path or (artifacts_dir / "mechanical" / "normative_sentence_selection.json")
    output_path = arguments.output_path or (artifacts_dir / "llm" / "sentence_context_selection.json")
    print(f"[sentence-context-selection] loading tasks from {tasks_path}", flush=True)
    tasks = sentence_context_selection.load_sentence_selection_tasks(tasks_path)
    if output_path.exists():
        existing_report = sentence_context_selection.load_context_selection_report(output_path)
        existing_validation = sentence_context_selection.validate_existing_report(existing_report, tasks)
        if existing_validation.is_reusable:
            print(f"[sentence-context-selection] skip existing report: {output_path}")
            print(f"[sentence-context-selection] selections={len(existing_report.selections)}")
            print(f"[sentence-context-selection] conflicts={len(existing_report.conflicts)}")
            print(
                "[sentence-context-selection] "
                f"invalid_context_selections={len(existing_report.invalid_context_selections)}",
            )
            print(f"[sentence-context-selection] retry_attempts={len(existing_report.retry_attempts)}")
            return
        print(
            f"[sentence-context-selection] existing report is not reusable: {existing_validation.reason}",
            flush=True,
        )
    print(
        f"[sentence-context-selection] running codex for {len(tasks)} tasks "
        f"(model={arguments.model or 'codex default'}, timeout={arguments.timeout_seconds}s, "
        f"max_retries={arguments.max_retries}, batch_size={arguments.batch_size}, "
        f"stream_codex_output={arguments.stream_codex_output})",
        flush=True,
    )
    report = sentence_context_selection.select_sentence_contexts_with_codex(
        tasks,
        codex_command=arguments.codex_command,
        model=arguments.model,
        timeout_seconds=arguments.timeout_seconds,
        max_retries=arguments.max_retries,
        batch_size=arguments.batch_size,
        stream_output=arguments.stream_codex_output,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[sentence-context-selection] writing report to {output_path}", flush=True)
    sentence_context_selection.save_context_selection_report(report, output_path)
    print(f"[sentence-context-selection] selections={len(report.selections)}")
    print(f"[sentence-context-selection] conflicts={len(report.conflicts)}")
    print(f"[sentence-context-selection] invalid_context_selections={len(report.invalid_context_selections)}")
    print(f"[sentence-context-selection] retry_attempts={len(report.retry_attempts)}")
    for invalid_selection in report.invalid_context_selections[:10]:
        print(
            "[sentence-context-selection] invalid "
            f"task={invalid_selection.task_id} sentence_id={invalid_selection.sentence_id} "
            f"reason={invalid_selection.reason}",
        )
    if len(report.invalid_context_selections) > 10:
        print(
            f"[sentence-context-selection] invalid ... {len(report.invalid_context_selections) - 10} more",
        )


def _run_constraint_drafts(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    artifacts_dir = project_root / CONSTRAINT_ARTIFACTS_DIR
    tasks_path = arguments.tasks_path or (artifacts_dir / "mechanical" / "normative_sentence_selection.json")
    context_selection_path = arguments.context_selection_path or (
        artifacts_dir / "llm" / "sentence_context_selection.json"
    )
    output_path = arguments.output_path or (artifacts_dir / "llm" / "constraint_drafts.json")
    print(f"[constraint-drafts] loading tasks from {tasks_path}", flush=True)
    sentence_tasks = sentence_context_selection.load_sentence_selection_tasks(tasks_path)
    print(f"[constraint-drafts] loading context selections from {context_selection_path}", flush=True)
    context_report = sentence_context_selection.load_context_selection_report(context_selection_path)
    tasks = sentence_constraint_candidate.build_constraint_candidate_tasks(sentence_tasks, context_report)
    if output_path.exists():
        existing_report = sentence_constraint_candidate.load_constraint_candidate_report(output_path)
        existing_validation = sentence_constraint_candidate.validate_existing_report(existing_report, tasks)
        if existing_validation.is_reusable:
            print(f"[constraint-drafts] skip existing report: {output_path}")
            print(f"[constraint-drafts] drafts={len(existing_report.candidates)}")
            print(f"[constraint-drafts] retry_attempts={len(existing_report.retry_attempts)}")
            return
        print(
            f"[constraint-drafts] existing report is not reusable: {existing_validation.reason}",
            flush=True,
        )
    print(
        f"[constraint-drafts] running codex for {len(tasks)} tasks "
        f"(model={arguments.model or 'codex default'}, timeout={arguments.timeout_seconds}s, "
        f"max_retries={arguments.max_retries}, batch_size={arguments.batch_size}, "
        f"stream_codex_output={arguments.stream_codex_output})",
        flush=True,
    )
    report = sentence_constraint_candidate.select_constraint_candidates_with_codex(
        tasks,
        codex_command=arguments.codex_command,
        model=arguments.model,
        timeout_seconds=arguments.timeout_seconds,
        max_retries=arguments.max_retries,
        batch_size=arguments.batch_size,
        stream_output=arguments.stream_codex_output,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[constraint-drafts] writing report to {output_path}", flush=True)
    sentence_constraint_candidate.save_constraint_candidate_report(report, output_path)
    print(f"[constraint-drafts] drafts={len(report.candidates)}")
    print(f"[constraint-drafts] retry_attempts={len(report.retry_attempts)}")


def _run_constraint_interpretations(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    artifacts_dir = project_root / CONSTRAINT_ARTIFACTS_DIR
    constraint_drafts_path = arguments.constraint_drafts_path or (artifacts_dir / "llm" / "constraint_drafts.json")
    output_path = arguments.output_path or (artifacts_dir / "llm" / "constraint_interpretations.json")
    print(f"[constraint-interpretations] loading constraint drafts from {constraint_drafts_path}", flush=True)
    draft_report = sentence_constraint_candidate.load_constraint_candidate_report(constraint_drafts_path)
    tasks = sentence_interpretation.build_interpretation_tasks(draft_report)
    if output_path.exists():
        existing_report = sentence_interpretation.load_interpretation_report(output_path)
        existing_validation = sentence_interpretation.validate_existing_report(existing_report, tasks)
        if existing_validation.is_reusable:
            print(f"[constraint-interpretations] skip existing report: {output_path}")
            print(f"[constraint-interpretations] interpretations={len(existing_report.interpretations)}")
            print(f"[constraint-interpretations] retry_attempts={len(existing_report.retry_attempts)}")
            return
        print(
            f"[constraint-interpretations] existing report is not reusable: {existing_validation.reason}",
            flush=True,
        )
    print(
        f"[constraint-interpretations] running codex for {len(tasks)} tasks "
        f"(model={arguments.model or 'codex default'}, timeout={arguments.timeout_seconds}s, "
        f"max_retries={arguments.max_retries}, batch_size={arguments.batch_size}, "
        f"stream_codex_output={arguments.stream_codex_output})",
        flush=True,
    )
    report = sentence_interpretation.select_interpretations_with_codex(
        tasks,
        codex_command=arguments.codex_command,
        model=arguments.model,
        timeout_seconds=arguments.timeout_seconds,
        max_retries=arguments.max_retries,
        batch_size=arguments.batch_size,
        stream_output=arguments.stream_codex_output,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[constraint-interpretations] writing report to {output_path}", flush=True)
    sentence_interpretation.save_interpretation_report(report, output_path)
    print(f"[constraint-interpretations] interpretations={len(report.interpretations)}")
    print(f"[constraint-interpretations] retry_attempts={len(report.retry_attempts)}")


def _run_kube_api_linter_hints(arguments: argparse.Namespace) -> None:
    project_root = Path(__file__).resolve().parents[2]
    artifacts_dir = project_root / CONSTRAINT_ARTIFACTS_DIR
    constraint_drafts_path = arguments.constraint_drafts_path or (artifacts_dir / "llm" / "constraint_drafts.json")
    output_path = arguments.output_path or (artifacts_dir / "llm" / "kube_api_linter_hints.json")
    print(
        f"[kube-api-linter-hints] loading constraint drafts from {constraint_drafts_path}",
        flush=True,
    )
    draft_report = sentence_constraint_candidate.load_constraint_candidate_report(constraint_drafts_path)
    tasks = kube_api_linter_relation.build_relation_tasks(draft_report)
    if output_path.exists():
        existing_report = kube_api_linter_relation.load_relation_report(output_path)
        existing_validation = kube_api_linter_relation.validate_existing_report(existing_report, tasks)
        if existing_validation.is_reusable:
            related = sum(1 for relation in existing_report.relations if relation.rules)
            print(f"[kube-api-linter-hints] skip existing report: {output_path}")
            print(f"[kube-api-linter-hints] hints={len(existing_report.relations)}")
            print(f"[kube-api-linter-hints] related={related}/{len(existing_report.relations)}")
            return
        print(
            f"[kube-api-linter-hints] existing report is not reusable: {existing_validation.reason}",
            flush=True,
        )
    print(f"[kube-api-linter-hints] selecting deterministic hints for {len(tasks)} tasks", flush=True)
    report = kube_api_linter_relation.select_related_rules(tasks)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[kube-api-linter-hints] writing report to {output_path}", flush=True)
    kube_api_linter_relation.save_relation_report(report, output_path)
    related = sum(1 for relation in report.relations if relation.rules)
    print(f"[kube-api-linter-hints] hints={len(report.relations)}")
    print(f"[kube-api-linter-hints] related={related}/{len(report.relations)}")


def _build_review_row(
    candidate: sentence_constraint_candidate.SentenceConstraintCandidate,
    *,
    interpretation: str,
    kube_api_linter_rules: tuple[str, ...],
) -> dict[str, str]:
    return {
        "ID": candidate.id,
        "Source-Span": candidate.source_span,
        "Source_Strength": ";".join(candidate.source_strength),
        "Original": candidate.original,
        "Constraint": candidate.constraint,
        "Interpretation": interpretation,
        "Kube-API-Linter": ";".join(kube_api_linter_rules),
        "Atomic": "",
        "Beyond-Syntax": "",
        "Diff-Closed": "",
        "Objective": "",
        "Grounded": "",
        "Decision(Auto)": "",
        "Notes": "",
    }


def _write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_SHEET_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
