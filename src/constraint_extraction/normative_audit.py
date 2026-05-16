"""Audit helpers for keyword-bearing normative statements."""

from __future__ import annotations

import enum
import json
import re
from pathlib import Path

import base
import normative_constraint
import pydantic

_HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_KEYWORD_RE = re.compile(
    r"\b("
    r"MUST(?: NOT)?|SHOULD(?: NOT)?|MAY(?: NOT)?|"
    r"must(?: not)?|should(?: not)?|may(?: not)?|"
    r"required|recommended|preferred|deprecated"
    r")\b",
)
_OBLIGATION_RE = re.compile(r"\bMUST\b(?!\s+NOT\b)|\bmust\b(?!\s+not\b)|\brequired\b")
_RECOMMENDATION_RE = re.compile(
    r"\bSHOULD\b(?!\s+NOT\b)|\bshould\b(?!\s+not\b)|\brecommended\b|\bpreferred\b",
)
_PROHIBITION_RE = re.compile(
    r"\bMUST\s+NOT\b|\bmust\s+not\b|"
    r"\bSHOULD\s+NOT\b|\bshould\s+not\b|"
    r"(?:^|[,:;]\s+)[Dd]o\s+not\b|"
    r"(?:^|[,:;]\s+)[Dd]on't\b|"
    r"^[Aa]void\b",
)
_DEPRECATION_RE = re.compile(r"\bdeprecated\b")
_PERMISSIVE_RE = re.compile(r"\bMAY(?:\s+NOT)?\b|\bmay(?:\s+not)?\b|\boptional(?:ly)?\b|\bcan\b")


class CandidateKind(enum.StrEnum):
    """Source unit kinds for extracted candidates."""

    PARAGRAPH_SENTENCE = "paragraph_sentence"
    BULLET = "bullet"


class AuditStatus(enum.StrEnum):
    """Coverage status of an extracted candidate."""

    MATCHED = "matched"
    UNMATCHED = "unmatched"


class SignalTag(enum.StrEnum):
    """Internal source wording tags used for extraction audit."""

    OBLIGATION = "obligation"
    RECOMMENDATION = "recommendation"
    PROHIBITION = "prohibition"
    DEPRECATION = "deprecation"
    PERMISSIVE = "permissive"


class SelectionStatus(enum.StrEnum):
    """Whether a signal-bearing sentence becomes a sentence selection task."""

    INCLUDED = "included"
    EXCLUDED = "excluded"


class KeywordCandidate(base.FrozenModel):
    """A single keyword-bearing normative candidate extracted from the document."""

    source_span: str
    section: str
    kind: CandidateKind
    text: str
    lead_in_span: str | None = None


class SourceSentence(base.FrozenModel):
    """A source sentence split from one original guideline block."""

    id: str
    text: str
    has_keyword: bool
    signal_tags: tuple[SignalTag, ...] = ()


class SentenceSelectionTask(base.FrozenModel):
    """One keyword sentence plus neighboring source sentences for LLM selection."""

    id: str
    block_id: str
    source_span: str
    section: str
    kind: CandidateKind
    block_original: str
    main_sentence: SourceSentence
    shared_context_sentences: tuple[SourceSentence, ...] = ()
    context_sentences: tuple[SourceSentence, ...]


class ContextSelectionConflict(base.FrozenModel):
    """A context sentence selected for multiple main sentences in one block."""

    block_id: str
    sentence_id: str
    sentence_text: str
    task_ids: tuple[str, ...]


class SentenceSelectionAuditRecord(base.FrozenModel):
    """Internal audit record for a signal-bearing source sentence."""

    block_id: str
    source_span: str
    section: str
    kind: CandidateKind
    sentence: SourceSentence
    selection_status: SelectionStatus
    signal_tags: tuple[SignalTag, ...]
    exclusion_reason: str | None = None


class SentenceSelectionArtifacts(base.FrozenModel):
    """Sentence selection tasks plus the internal inclusion audit."""

    tasks: tuple[SentenceSelectionTask, ...]
    audit_records: tuple[SentenceSelectionAuditRecord, ...]


class KeywordNormativeRule(base.FrozenModel):
    """Keyword-bearing normative rule extracted one-by-one from the document."""

    id: str
    source_path: Path
    source_span: str
    lead_in_span: str | None = None
    section: str
    kind: CandidateKind
    text: str
    strength_signal: normative_constraint.NormativeSignal

    @pydantic.field_validator("source_path", mode="before")
    @classmethod
    def validate_source_path(cls, value: object) -> object:
        """Allow serialized path strings."""
        if isinstance(value, str):
            return Path(value)
        return value

    @pydantic.field_validator("kind", mode="before")
    @classmethod
    def validate_kind(cls, value: object) -> object:
        """Allow serialized candidate kind strings."""
        if isinstance(value, str):
            return CandidateKind(value)
        return value

    @pydantic.field_validator("strength_signal", mode="before")
    @classmethod
    def validate_strength_signal(cls, value: object) -> object:
        """Allow serialized strength signal strings."""
        if isinstance(value, str):
            return normative_constraint.NormativeSignal(value)
        return value


class CandidateAuditRecord(base.FrozenModel):
    """Audit outcome for one extracted candidate."""

    candidate: KeywordCandidate
    status: AuditStatus
    matched_normative_ids: tuple[str, ...]


class NormativeAuditResult(base.FrozenModel):
    """Coverage audit result for keyword-bearing candidates."""

    total_candidates: int
    matched_candidates: int
    unmatched_candidates: int
    records: tuple[CandidateAuditRecord, ...]


def extract_keyword_candidates(document_text: str) -> tuple[KeywordCandidate, ...]:
    """Extract one candidate per bullet or per sentence with a strength keyword."""
    blocks = _collect_blocks(document_text)
    candidates: list[KeywordCandidate] = []
    pending_bullet_lead_in: tuple[str, str] | None = None
    for start_line, end_line, section, kind, block_text in blocks:
        if kind == CandidateKind.BULLET:
            normalized = _normalize_block_text(block_text)
            lead_in_span = None
            if pending_bullet_lead_in is not None:
                lead_in_text, lead_in_span = pending_bullet_lead_in
                normalized = f"{lead_in_text} {normalized}"
            if _KEYWORD_RE.search(normalized):
                candidates.append(
                    KeywordCandidate(
                        source_span=f"{start_line}-{end_line}",
                        section=section,
                        kind=kind,
                        text=normalized,
                        lead_in_span=lead_in_span,
                    ),
                )
            continue
        pending_bullet_lead_in = None
        sentences = _split_paragraph_sentences(block_text)
        if _is_bullet_lead_in(block_text):
            lead_in_text = _normalize_block_text(block_text)
            pending_bullet_lead_in = (lead_in_text, f"{start_line}-{end_line}")
            continue
        candidates.extend(
            KeywordCandidate(
                source_span=f"{start_line}-{end_line}",
                section=section,
                kind=kind,
                text=sentence,
            )
            for sentence in sentences
            if _KEYWORD_RE.search(sentence)
        )
    return tuple(candidates)


def extract_sentence_selection_tasks(document_text: str) -> tuple[SentenceSelectionTask, ...]:
    """Extract keyword sentences with their original block and nearby context candidates."""
    return extract_sentence_selection_artifacts(document_text).tasks


def extract_sentence_selection_artifacts(document_text: str) -> SentenceSelectionArtifacts:
    """Extract sentence selection tasks and the inclusion audit."""
    tasks: list[SentenceSelectionTask] = []
    audit_records: list[SentenceSelectionAuditRecord] = []
    for block_index, (start_line, end_line, section, kind, block_text) in enumerate(
        _collect_blocks(document_text),
        1,
    ):
        block_id = f"block_{block_index:04d}"
        block_original = _normalize_block_text(block_text)
        sentences = _source_sentences(block_text)
        keyword_positions = tuple(index for index, sentence in enumerate(sentences) if sentence.has_keyword)
        shared_context_sentences = _shared_context_sentences(sentences, keyword_positions)
        audit_records.extend(
            _sentence_selection_audit_record(
                block_id=block_id,
                source_span=f"{start_line}-{end_line}",
                section=section,
                kind=kind,
                sentence=sentence,
            )
            for sentence in sentences
            if sentence.signal_tags
        )
        tasks.extend(
            SentenceSelectionTask(
                id=f"{block_id}_{sentences[keyword_position].id}",
                block_id=block_id,
                source_span=f"{start_line}-{end_line}",
                section=section,
                kind=kind,
                block_original=block_original,
                main_sentence=sentences[keyword_position],
                shared_context_sentences=shared_context_sentences,
                context_sentences=_bounded_context_sentences(
                    sentences=sentences,
                    keyword_positions=keyword_positions,
                    keyword_position_index=keyword_position_index,
                ),
            )
            for keyword_position_index, keyword_position in enumerate(keyword_positions)
        )
    return SentenceSelectionArtifacts(tasks=tuple(tasks), audit_records=tuple(audit_records))


def build_selected_original(task: SentenceSelectionTask, selected_context_sentence_ids: tuple[str, ...]) -> str:
    """Build an exact original excerpt from selected context sentence IDs."""
    unknown_ids = _unknown_context_sentence_ids(task, selected_context_sentence_ids)
    if unknown_ids:
        msg = f"Unknown context sentence IDs for {task.id}: {', '.join(unknown_ids)}"
        raise ValueError(msg)
    selected_ids = frozenset((*selected_context_sentence_ids, task.main_sentence.id))
    sentences = (task.main_sentence, *task.shared_context_sentences, *task.context_sentences)
    ordered_sentences = sorted(
        (sentence for sentence in sentences if sentence.id in selected_ids),
        key=lambda sentence: _sentence_number(sentence.id),
    )
    return " ".join(sentence.text for sentence in ordered_sentences)


def find_context_selection_conflicts(
    tasks: tuple[SentenceSelectionTask, ...],
    selections_by_task_id: dict[str, tuple[str, ...]],
) -> tuple[ContextSelectionConflict, ...]:
    """Find non-shared context sentences selected for multiple main sentences."""
    tasks_by_id = {task.id: task for task in tasks}
    unknown_task_ids = tuple(task_id for task_id in selections_by_task_id if task_id not in tasks_by_id)
    if unknown_task_ids:
        msg = f"Unknown sentence selection task IDs: {', '.join(unknown_task_ids)}"
        raise ValueError(msg)

    task_ids_by_context_id: dict[tuple[str, str], list[str]] = {}
    text_by_context_id: dict[tuple[str, str], str] = {}
    for task_id, selected_context_sentence_ids in selections_by_task_id.items():
        task = tasks_by_id[task_id]
        unknown_ids = _unknown_context_sentence_ids(task, selected_context_sentence_ids)
        if unknown_ids:
            msg = f"Unknown context sentence IDs for {task.id}: {', '.join(unknown_ids)}"
            raise ValueError(msg)

        context_text_by_sentence_id = {sentence.id: sentence.text for sentence in task.context_sentences}
        for sentence_id in selected_context_sentence_ids:
            if sentence_id not in context_text_by_sentence_id:
                continue
            key = (task.block_id, sentence_id)
            task_ids_by_context_id.setdefault(key, []).append(task.id)
            text_by_context_id[key] = context_text_by_sentence_id[sentence_id]

    conflicts = [
        ContextSelectionConflict(
            block_id=block_id,
            sentence_id=sentence_id,
            sentence_text=text_by_context_id[(block_id, sentence_id)],
            task_ids=tuple(dict.fromkeys(task_ids)),
        )
        for (block_id, sentence_id), task_ids in task_ids_by_context_id.items()
        if len(dict.fromkeys(task_ids)) > 1
    ]
    conflicts.sort(key=lambda conflict: (conflict.block_id, _sentence_number(conflict.sentence_id)))
    return tuple(conflicts)


def audit_normative_coverage(
    candidates: tuple[KeywordCandidate, ...],
    constraints: tuple[normative_constraint.NormativeConstraint, ...],
) -> NormativeAuditResult:
    """Compare extracted candidates against the current normative catalog."""
    normalized_constraints = tuple(
        (constraint.id, _normalize_for_match(constraint.text)) for constraint in constraints
    )
    records: list[CandidateAuditRecord] = []
    for candidate in candidates:
        normalized_candidate = _normalize_for_match(candidate.text)
        matched_ids = tuple(
            constraint_id
            for constraint_id, normalized_text in normalized_constraints
            if normalized_candidate == normalized_text
            or normalized_candidate in normalized_text
            or normalized_text in normalized_candidate
        )
        status = AuditStatus.MATCHED if matched_ids else AuditStatus.UNMATCHED
        records.append(
            CandidateAuditRecord(
                candidate=candidate,
                status=status,
                matched_normative_ids=matched_ids,
            ),
        )
    matched_count = sum(record.status == AuditStatus.MATCHED for record in records)
    return NormativeAuditResult(
        total_candidates=len(records),
        matched_candidates=matched_count,
        unmatched_candidates=len(records) - matched_count,
        records=tuple(records),
    )


def materialize_keyword_normative_rules(
    candidates: tuple[KeywordCandidate, ...],
    source_path: Path,
) -> tuple[KeywordNormativeRule, ...]:
    """Convert extracted candidates into JSON-ready keyword-bearing rules."""
    rules: list[KeywordNormativeRule] = []
    for index, candidate in enumerate(candidates, 1):
        rules.append(
            KeywordNormativeRule(
                id=f"kw_norm_{index:03d}",
                source_path=source_path,
                source_span=candidate.source_span,
                lead_in_span=candidate.lead_in_span,
                section=candidate.section,
                kind=candidate.kind,
                text=candidate.text,
                strength_signal=infer_strength_signal(candidate.text),
            ),
        )
    return tuple(rules)


def save_keyword_normative_rules(
    rules: tuple[KeywordNormativeRule, ...],
    output_path: Path,
) -> None:
    """Save keyword-bearing normative rules as JSON."""
    payload = {"constraints": [rule.model_dump(mode="json") for rule in rules]}
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_sentence_selection_tasks(
    tasks: tuple[SentenceSelectionTask, ...],
    output_path: Path,
) -> None:
    """Save sentence selection tasks for one-shot LLM normalization."""
    payload = {"tasks": [task.model_dump(mode="json") for task in tasks]}
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_sentence_selection_audit(
    audit_records: tuple[SentenceSelectionAuditRecord, ...],
    output_path: Path,
) -> None:
    """Save sentence selection inclusion audit as JSON."""
    payload = {
        "summary": {
            "included": sum(record.selection_status == SelectionStatus.INCLUDED for record in audit_records),
            "excluded": sum(record.selection_status == SelectionStatus.EXCLUDED for record in audit_records),
        },
        "records": [record.model_dump(mode="json") for record in audit_records],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def render_audit_markdown(audit_result: NormativeAuditResult) -> str:
    """Render a markdown summary for a normative keyword audit."""
    lines = [
        "# Normative Keyword Audit",
        "",
        f"- Total candidates: `{audit_result.total_candidates}`",
        f"- Matched candidates: `{audit_result.matched_candidates}`",
        f"- Unmatched candidates: `{audit_result.unmatched_candidates}`",
        "",
        "## Unmatched Candidates",
        "",
    ]
    unmatched = [record for record in audit_result.records if record.status == AuditStatus.UNMATCHED]
    if not unmatched:
        lines.append("None.")
    else:
        lines.extend(
            f"- `{record.candidate.source_span}` [{record.candidate.section}] {record.candidate.text}"
            for record in unmatched
        )
    return "\n".join(lines).strip() + "\n"


def save_audit_json(audit_result: NormativeAuditResult, output_path: Path) -> None:
    """Save the audit result as JSON."""
    output_path.write_text(
        json.dumps(audit_result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def infer_strength_signal(text: str) -> normative_constraint.NormativeSignal:
    """Infer one representative strength signal from a keyword-bearing text."""
    scored_patterns = (
        (0, re.compile(r"\bMUST(?: NOT)?\b"), normative_constraint.NormativeSignal.MUST_UPPER),
        (1, re.compile(r"\bmust(?: not)?\b"), normative_constraint.NormativeSignal.MUST),
        (2, re.compile(r"\brequired\b"), normative_constraint.NormativeSignal.REQUIRED),
        (3, re.compile(r"\bSHOULD(?: NOT)?\b"), normative_constraint.NormativeSignal.SHOULD_UPPER),
        (4, re.compile(r"\bshould(?: not)?\b"), normative_constraint.NormativeSignal.SHOULD),
        (5, re.compile(r"\brecommended\b"), normative_constraint.NormativeSignal.RECOMMENDED),
        (6, re.compile(r"\bpreferred\b"), normative_constraint.NormativeSignal.PREFERRED),
        (7, re.compile(r"\bMAY(?: NOT)?\b"), normative_constraint.NormativeSignal.MAY_UPPER),
        (8, re.compile(r"\bmay(?: not)?\b"), normative_constraint.NormativeSignal.MAY),
        (9, re.compile(r"\bdeprecated\b"), normative_constraint.NormativeSignal.DEPRECATED),
    )
    matches: list[tuple[int, int, normative_constraint.NormativeSignal]] = []
    for priority, pattern, signal in scored_patterns:
        match = pattern.search(text)
        if match:
            matches.append((priority, match.start(), signal))
    if not matches:
        raise ValueError(f"No strength keyword found in text: {text}")
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[0][2]


def _collect_blocks(document_text: str) -> tuple[tuple[int, int, str, CandidateKind, str], ...]:  # noqa: PLR0915
    """Collect markdown blocks while preserving bullet boundaries."""
    blocks: list[tuple[int, int, str, CandidateKind, str]] = []
    current_section = ""
    seen_first_section = False
    lines = document_text.splitlines()
    index = 0
    in_code_block = False

    while index < len(lines):
        line_number = index + 1
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            index += 1
            continue

        if in_code_block:
            index += 1
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            current_section = heading_match.group(2).strip()
            seen_first_section = True
            index += 1
            continue

        if not seen_first_section:
            index += 1
            continue

        if not stripped:
            index += 1
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            start_line = line_number
            bullet_lines = [bullet_match.group(3).strip()]
            index += 1
            while index < len(lines):
                next_line = lines[index]
                next_stripped = next_line.strip()
                if not next_stripped:
                    break
                if _HEADING_RE.match(next_line) or _BULLET_RE.match(next_line):
                    break
                bullet_lines.append(next_stripped)
                index += 1
            blocks.append(
                (
                    start_line,
                    index,
                    current_section,
                    CandidateKind.BULLET,
                    " ".join(bullet_lines).strip(),
                ),
            )
            continue

        start_line = line_number
        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            if (
                not next_stripped
                or next_stripped.startswith("```")
                or _HEADING_RE.match(next_line)
                or _BULLET_RE.match(next_line)
            ):
                break
            paragraph_lines.append(next_stripped)
            index += 1
        blocks.append(
            (
                start_line,
                index,
                current_section,
                CandidateKind.PARAGRAPH_SENTENCE,
                " ".join(paragraph_lines).strip(),
            ),
        )

    return tuple(blocks)


def _normalize_block_text(block_text: str) -> str:
    """Normalize whitespace and inline markdown for extracted text."""
    normalized = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", block_text)
    normalized = normalized.replace("**", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _split_paragraph_sentences(block_text: str) -> tuple[str, ...]:
    """Split a paragraph into sentence-like units without breaking wrapped lines."""
    normalized = _normalize_block_text(block_text)
    if not normalized:
        return ()
    protected = _protect_abbreviations(normalized)
    sentences = re.split(r"(?<=[.!?])\s+", protected)
    return tuple(_restore_abbreviations(sentence).strip() for sentence in sentences if sentence.strip())


def _source_sentences(block_text: str) -> tuple[SourceSentence, ...]:
    """Split one block into numbered source sentences."""
    source_sentences: list[SourceSentence] = []
    for index, sentence in enumerate(_split_paragraph_sentences(block_text), 1):
        signal_tags = _sentence_signal_tags(sentence)
        source_sentences.append(
            SourceSentence(
                id=f"s{index}",
                text=sentence,
                has_keyword=_is_included_signal(signal_tags),
                signal_tags=signal_tags,
            ),
        )
    return tuple(source_sentences)


def _sentence_selection_audit_record(
    *,
    block_id: str,
    source_span: str,
    section: str,
    kind: CandidateKind,
    sentence: SourceSentence,
) -> SentenceSelectionAuditRecord:
    """Build an audit record for one signal-bearing sentence."""
    selection_status = SelectionStatus.INCLUDED if sentence.has_keyword else SelectionStatus.EXCLUDED
    exclusion_reason = "permissive_only" if selection_status == SelectionStatus.EXCLUDED else None
    return SentenceSelectionAuditRecord(
        block_id=block_id,
        source_span=source_span,
        section=section,
        kind=kind,
        sentence=sentence,
        selection_status=selection_status,
        signal_tags=sentence.signal_tags,
        exclusion_reason=exclusion_reason,
    )


def _sentence_signal_tags(text: str) -> tuple[SignalTag, ...]:
    """Return internal source wording tags matched by a sentence."""
    tags: list[SignalTag] = []
    for pattern, tag in (
        (_OBLIGATION_RE, SignalTag.OBLIGATION),
        (_RECOMMENDATION_RE, SignalTag.RECOMMENDATION),
        (_PROHIBITION_RE, SignalTag.PROHIBITION),
        (_DEPRECATION_RE, SignalTag.DEPRECATION),
        (_PERMISSIVE_RE, SignalTag.PERMISSIVE),
    ):
        if pattern.search(text):
            tags.append(tag)
    return tuple(tags)


def _is_included_signal(signal_tags: tuple[SignalTag, ...]) -> bool:
    """Return whether signal tags are strong enough to become a task."""
    return any(tag != SignalTag.PERMISSIVE for tag in signal_tags)


def _unknown_context_sentence_ids(
    task: SentenceSelectionTask,
    selected_context_sentence_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Return selected IDs that are not available context sentences for a task."""
    known_context_ids = frozenset(
        sentence.id for sentence in (*task.shared_context_sentences, *task.context_sentences)
    )
    return tuple(sentence_id for sentence_id in selected_context_sentence_ids if sentence_id not in known_context_ids)


def _shared_context_sentences(
    sentences: tuple[SourceSentence, ...],
    keyword_positions: tuple[int, ...],
) -> tuple[SourceSentence, ...]:
    """Return block-leading non-keyword sentences available to every main sentence."""
    if not keyword_positions:
        return ()
    first_keyword_position = keyword_positions[0]
    return tuple(sentence for sentence in sentences[:first_keyword_position] if not sentence.has_keyword)


def _bounded_context_sentences(
    *,
    sentences: tuple[SourceSentence, ...],
    keyword_positions: tuple[int, ...],
    keyword_position_index: int,
) -> tuple[SourceSentence, ...]:
    """Return non-keyword context bounded by neighboring keyword sentences."""
    keyword_position = keyword_positions[keyword_position_index]
    previous_keyword_position = keyword_positions[keyword_position_index - 1] if keyword_position_index > 0 else None
    next_keyword_position = (
        keyword_positions[keyword_position_index + 1] if keyword_position_index < len(keyword_positions) - 1 else None
    )
    start_position = keyword_position + 1 if previous_keyword_position is None else previous_keyword_position + 1
    end_position = next_keyword_position if next_keyword_position is not None else len(sentences)
    return tuple(sentence for sentence in sentences[start_position:end_position] if not sentence.has_keyword)


def _sentence_number(sentence_id: str) -> int:
    """Return the numeric part of sentence IDs such as s1."""
    return int(sentence_id.removeprefix("s"))


def _is_bullet_lead_in(block_text: str) -> bool:
    """Return whether a paragraph is an introducing sentence for following bullets."""
    normalized = _normalize_block_text(block_text)
    if not normalized.endswith(":"):
        return False
    last_sentence = _last_sentence(normalized)
    if _KEYWORD_RE.search(last_sentence) is None:
        return False
    return True


def _protect_abbreviations(text: str) -> str:
    """Protect common abbreviations from sentence splitting."""
    replacements = {
        "e.g.": "e<DOT>g<DOT>",
        "i.e.": "i<DOT>e<DOT>",
        "etc.": "etc<DOT>",
        "vs.": "vs<DOT>",
    }
    protected = text
    for original, placeholder in replacements.items():
        protected = protected.replace(original, placeholder)
        protected = protected.replace(original.capitalize(), placeholder.capitalize())
    return protected


def _restore_abbreviations(text: str) -> str:
    """Restore protected abbreviations after sentence splitting."""
    replacements = {
        "e<DOT>g<DOT>": "e.g.",
        "E<DOT>g<DOT>": "E.g.",
        "i<DOT>e<DOT>": "i.e.",
        "I<DOT>e<DOT>": "I.e.",
        "etc<DOT>": "etc.",
        "Etc<DOT>": "Etc.",
        "vs<DOT>": "vs.",
        "Vs<DOT>": "Vs.",
    }
    restored = text
    for placeholder, original in replacements.items():
        restored = restored.replace(placeholder, original)
    return restored


def _last_sentence(text: str) -> str:
    """Return the last sentence-like unit of a paragraph."""
    protected = _protect_abbreviations(text)
    sentences = re.split(r"(?<=[.!?])\s+", protected)
    if not sentences:
        return text
    return _restore_abbreviations(sentences[-1]).strip()


def _normalize_for_match(text: str) -> str:
    """Normalize text for approximate matching."""
    normalized = re.sub(r"`([^`]+)`", r"\1", text)
    normalized = re.sub(r"\[[^\]]+\]\([^\)]+\)", "", normalized)
    normalized = normalized.replace("**", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().lower()
