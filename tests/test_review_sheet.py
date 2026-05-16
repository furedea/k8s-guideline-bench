"""Tests for the review-sheet subcommand of constraint_extraction/main.py."""

import csv
import json
from pathlib import Path

import main


def test_review_sheet_fieldnames_match_updated_atomic_review_schema() -> None:
    assert main.REVIEW_SHEET_FIELDNAMES == [
        "ID",
        "Source-Span",
        "Source_Strength",
        "Original",
        "Constraint",
        "Interpretation",
        "Atomic",
        "Beyond-Syntax",
        "Diff-Closed",
        "Objective",
        "Grounded",
        "Decision(Auto)",
        "Notes",
    ]


def test_build_review_row_initializes_human_review_columns() -> None:
    row = main._build_review_row(
        main.sentence_constraint_candidate.SentenceConstraintCandidate(
            id="block_0001_s1",
            task_id="block_0001_s1",
            source_span="10-12",
            source_strength=("obligation", "prohibition"),
            original="Original source text.",
            constraint="Draft constraint.",
        ),
        interpretation="Interpretation text.",
    )

    assert row["ID"] == "block_0001_s1"
    assert row["Source-Span"] == "10-12"
    assert row["Source_Strength"] == "obligation;prohibition"
    assert row["Original"] == "Original source text."
    assert row["Constraint"] == "Draft constraint."
    assert row["Interpretation"] == "Interpretation text."
    assert row["Atomic"] == ""
    assert row["Beyond-Syntax"] == ""
    assert row["Diff-Closed"] == ""
    assert row["Objective"] == ""
    assert row["Grounded"] == ""
    assert row["Decision(Auto)"] == ""
    assert row["Notes"] == ""
    assert "scoped" not in row


def test_run_review_sheet_writes_rows_from_draft_constraints_and_interpretations(tmp_path: Path) -> None:
    candidates_path = tmp_path / "sentence_constraint_candidates.json"
    interpretations_path = tmp_path / "sentence_interpretations.json"
    output_path = tmp_path / "review.csv"
    candidates_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "block_0001_s1",
                        "task_id": "block_0001_s1",
                        "source_span": "10-12",
                        "source_strength": ["obligation"],
                        "original": "Original source text.",
                        "constraint": "Draft constraint.",
                    },
                ],
                "retry_attempts": [],
            },
        ),
        encoding="utf-8",
    )
    interpretations_path.write_text(
        json.dumps(
            {
                "interpretations": [
                    {
                        "task_id": "block_0001_s1",
                        "source_span": "10-12",
                        "source_strength": ["obligation"],
                        "original": "Original source text.",
                        "constraint": "Draft constraint.",
                        "interpretation": "Interpretation text.",
                    },
                ],
                "retry_attempts": [],
            },
        ),
        encoding="utf-8",
    )

    main._run_review_sheet(
        main.argparse.Namespace(
            constraint_candidates_path=candidates_path,
            interpretations_path=interpretations_path,
            output_path=output_path,
        ),
    )

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows == [
        {
            "ID": "block_0001_s1",
            "Source-Span": "10-12",
            "Source_Strength": "obligation",
            "Original": "Original source text.",
            "Constraint": "Draft constraint.",
            "Interpretation": "Interpretation text.",
            "Atomic": "",
            "Beyond-Syntax": "",
            "Diff-Closed": "",
            "Objective": "",
            "Grounded": "",
            "Decision(Auto)": "",
            "Notes": "",
        },
    ]
