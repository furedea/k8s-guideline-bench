"""Guideline source selection based on refactoring commit landscape."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import base
import pydantic

DEFAULT_MINIMUM_MATCH_COUNT = 3
MAX_EXAMPLES_PER_SOURCE = 5


class RefactorCommit(base.FrozenModel):
    """Refactoring-like commit metadata used for source selection."""

    sha: str
    date: str
    subject: str


class GuidelineSource(base.FrozenModel):
    """Explicit guideline document candidate."""

    id: str
    title: str
    path: Path
    summary: str
    keyword_patterns: tuple[str, ...]
    rationale: str

    @pydantic.field_validator("path", mode="before")
    @classmethod
    def validate_path(cls, value: object) -> object:
        """Allow serialized path strings."""
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("keyword_patterns", mode="before")
    @classmethod
    def validate_keyword_patterns(cls, value: object) -> object:
        """Allow serialized list values for keyword patterns."""
        if isinstance(value, list):
            return tuple(value)
        return value


class SourceCoverage(base.FrozenModel):
    """Coverage summary for a single guideline source."""

    source: GuidelineSource
    matched_commit_count: int
    matched_examples: tuple[RefactorCommit, ...]
    selected: bool


_REFORMAT_REGEX_FLAGS = re.IGNORECASE


def collect_refactor_commits(
    repo_path: Path,
    target_paths: tuple[str, ...],
    since: str,
    grep: str,
) -> tuple[RefactorCommit, ...]:
    """Collect refactoring-like commit subjects from git history."""
    command = [
        "git",
        "log",
        "--no-merges",
        f"--since={since}",
        "--regexp-ignore-case",
        "--extended-regexp",
        f"--grep={grep}",
        "--date=short",
        "--pretty=format:%H%x1f%ad%x1f%s",
        "--",
        *target_paths,
    ]
    raw_output = subprocess.check_output(command, cwd=repo_path, text=True)
    commits: list[RefactorCommit] = []
    for line in raw_output.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        commits.append(
            RefactorCommit(
                sha=parts[0],
                date=parts[1],
                subject=parts[2],
            ),
        )
    return tuple(commits)


def select_guideline_sources(
    sources: tuple[GuidelineSource, ...],
    commits: tuple[RefactorCommit, ...],
    minimum_match_count: int = DEFAULT_MINIMUM_MATCH_COUNT,
) -> tuple[SourceCoverage, ...]:
    """Select explicit guideline sources based on commit-subject coverage."""
    coverage_summaries: list[SourceCoverage] = []
    for source in sources:
        matched_commits = tuple(
            commit for commit in commits if _matches_source_patterns(commit.subject, source.keyword_patterns)
        )
        coverage_summaries.append(
            SourceCoverage(
                source=source,
                matched_commit_count=len(matched_commits),
                matched_examples=matched_commits[:MAX_EXAMPLES_PER_SOURCE],
                selected=len(matched_commits) >= minimum_match_count,
            ),
        )
    return tuple(
        sorted(
            coverage_summaries,
            key=lambda item: (-item.matched_commit_count, item.source.id),
        ),
    )


def save_selection_report(
    output_path: Path,
    coverage: tuple[SourceCoverage, ...],
    repo_path: Path,
) -> None:
    """Write a machine-readable JSON selection report."""
    document = {
        "sources": [
            {
                "id": item.source.id,
                "title": item.source.title,
                "path": _display_path(item.source.path, repo_path),
                "summary": item.source.summary,
                "rationale": item.source.rationale,
                "matched_commit_count": item.matched_commit_count,
                "selected": item.selected,
                "matched_examples": [
                    {
                        "sha": example.sha,
                        "date": example.date,
                        "subject": example.subject,
                    }
                    for example in item.matched_examples
                ],
            }
            for item in coverage
        ],
    }
    output_path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def render_selection_markdown(
    coverage: tuple[SourceCoverage, ...],
    repo_path: Path,
) -> str:
    """Render a human-readable source selection report."""
    sections = [
        "# Guideline Source Selection",
        "",
        "| Source | Matches | Selected | Path |",
        "|---|---:|:---:|---|",
    ]
    for item in coverage:
        selected_mark = "yes" if item.selected else "no"
        sections.append(
            f"| {item.source.title} | {item.matched_commit_count} | {selected_mark} | "
            f"`{_display_path(item.source.path, repo_path)}` |",
        )
    sections.append("")
    for item in coverage:
        sections.append(f"## {item.source.title}")
        sections.append(f"- Selected: {'yes' if item.selected else 'no'}")
        sections.append(f"- Matches: {item.matched_commit_count}")
        sections.append(f"- Rationale: {item.source.rationale}")
        if item.matched_examples:
            sections.append("- Example commits:")
            sections.extend(
                f"  - {example.date} `{example.sha[:12]}` {example.subject}" for example in item.matched_examples
            )
        sections.append("")
    return "\n".join(sections).strip() + "\n"


def _matches_source_patterns(subject: str, keyword_patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, subject, flags=_REFORMAT_REGEX_FLAGS) is not None for pattern in keyword_patterns)


def _display_path(path: Path, repo_path: Path) -> str:
    try:
        return str(path.relative_to(repo_path))
    except ValueError:
        return str(path)
