"""Tests for cleaning Kubernetes PR body boilerplate before prompt assembly."""

import pr_body


def test_clean_pr_body_strips_html_comments_across_lines() -> None:
    raw = "<!--\nthanks for the PR\n-->\nReal content.\n<!-- trailing note --> more"

    cleaned = pr_body.clean_pr_body(raw)

    assert cleaned == "Real content.\nmore"


def test_clean_pr_body_drops_standalone_prow_commands() -> None:
    raw = "#### What type of PR is this?\n/kind cleanup\n/sig api-machinery\n\nActual text."

    cleaned = pr_body.clean_pr_body(raw)

    assert "/kind" not in cleaned
    assert "/sig" not in cleaned
    assert "Actual text." in cleaned


def test_clean_pr_body_removes_empty_release_note_block() -> None:
    raw = "Before\n```release-note\nNONE\n```\nAfter"

    cleaned = pr_body.clean_pr_body(raw)

    assert "release-note" not in cleaned
    assert "Before" in cleaned
    assert "After" in cleaned


def test_clean_pr_body_keeps_non_empty_release_note_block() -> None:
    raw = "```release-note\nNew feature X enabled by default.\n```"

    cleaned = pr_body.clean_pr_body(raw)

    assert "New feature X" in cleaned
    assert "```release-note" in cleaned


def test_clean_pr_body_drops_empty_section_headings() -> None:
    raw = "#### Kept section\nReal body.\n\n#### Empty\n\n#### Next\nText."

    cleaned = pr_body.clean_pr_body(raw)

    assert "Kept section" in cleaned
    assert "Empty" not in cleaned
    assert "Next" in cleaned


def test_clean_pr_body_collapses_excess_blank_lines() -> None:
    raw = "A\n\n\n\n\nB"

    cleaned = pr_body.clean_pr_body(raw)

    assert cleaned == "A\n\nB"


def test_clean_pr_body_returns_empty_for_empty_input() -> None:
    assert pr_body.clean_pr_body("") == ""
