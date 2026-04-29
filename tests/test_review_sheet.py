"""Tests for the review-sheet subcommand of constraint_extraction/main.py."""

import main


def test_review_sheet_fieldnames_match_updated_atomic_review_schema() -> None:
    assert main.REVIEW_SHEET_FIELDNAMES == [
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


def test_build_row_initializes_updated_review_columns() -> None:
    row = main._build_row(
        norm={
            "id": "norm_001",
            "source_span": "1-2",
            "strength_signal": "must",
            "text": "Rule text.",
        },
        lines=["Original first line.\n", "Original second line.\n"],
        interpretations={"norm_001": "Interpretation text."},
    )

    assert row["id"] == "norm_001"
    assert row["source_span"] == "1-2"
    assert row["source_strength"] == "must"
    assert row["original"] == "Original first line. Original second line."
    assert row["text"] == "Rule text."
    assert row["interpretation"] == "Interpretation text."
    assert row["atomic"] == ""
    assert row["beyond_syntax"] == ""
    assert row["diff_code_related"] == ""
    assert row["objective"] == ""
    assert row["grounded"] == ""
    assert row["decision"] == ""
    assert row["notes"] == ""
    assert "scoped" not in row
