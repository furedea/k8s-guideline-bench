"""Clean Kubernetes PR body boilerplate before feeding it to an agent prompt."""

import re

_HTML_COMMENT_PATTERN = re.compile(r"[ \t]*<!--.*?-->[ \t]*", re.DOTALL)
_PROW_COMMAND_PATTERN = re.compile(r"^/[A-Za-z][\w-]*(?:\s+.*)?$")
_EMPTY_RELEASE_NOTE_PATTERN = re.compile(
    r"```release-note\s*\n\s*(?:NONE|N/A)?\s*\n```",
    re.IGNORECASE,
)
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+\S")


def clean_pr_body(raw: str) -> str:
    """Strip Kubernetes PR template boilerplate (comments, prow commands, empty sections)."""
    if not raw:
        return ""
    text = _HTML_COMMENT_PATTERN.sub("", raw)
    text = _EMPTY_RELEASE_NOTE_PATTERN.sub("", text)
    lines = [line for line in text.splitlines() if not _PROW_COMMAND_PATTERN.match(line.strip())]
    lines = _drop_empty_headings(lines)
    return _collapse_blank_lines(lines).strip()


def _drop_empty_headings(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for index, line in enumerate(lines):
        if _HEADING_PATTERN.match(line) and _heading_has_no_content(lines, index):
            continue
        kept.append(line)
    return kept


def _heading_has_no_content(lines: list[str], heading_index: int) -> bool:
    for line in lines[heading_index + 1 :]:
        if _HEADING_PATTERN.match(line):
            return True
        if line.strip():
            return False
    return True


def _collapse_blank_lines(lines: list[str]) -> str:
    result: list[str] = []
    blank_streak = 0
    for line in lines:
        if line.strip():
            result.append(line)
            blank_streak = 0
            continue
        blank_streak += 1
        if blank_streak <= 1:
            result.append("")
    return "\n".join(result)
