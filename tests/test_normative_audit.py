from pathlib import Path

import normative_audit
import normative_constraint


def test_extract_keyword_candidates_keeps_wrapped_bullet_as_one_candidate() -> None:
    document = """
## Section

- Controllers should apply their conditions to a resource
  the first time they visit the resource.
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 1
    assert candidates[0].kind == normative_audit.CandidateKind.BULLET
    assert "the first time they visit the resource." in candidates[0].text


def test_extract_keyword_candidates_ignores_code_blocks() -> None:
    document = """
## Section

```go
// +required
```

Fields must be either optional or required.
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 1
    assert candidates[0].text == "Fields must be either optional or required."


def test_extract_keyword_candidates_ignores_preamble_before_first_section() -> None:
    document = """
Intro text should not be collected.

## Section

Fields must be either optional or required.
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 1
    assert candidates[0].section == "Section"


def test_extract_keyword_candidates_preserves_markdown_link_text() -> None:
    document = """
## Section

Lists should support label filtering (see [the labels documentation](https://example.com)).
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 1
    assert "the labels documentation" in candidates[0].text


def test_extract_keyword_candidates_merges_keyword_lead_in_into_bullets() -> None:
    document = """
## Section

All JSON objects returned by an API MUST have the following fields:

* kind: a string that identifies the schema this object should have
* apiVersion: a string that identifies the version of the schema the object should have
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 2
    assert candidates[0].lead_in_span == "3-3"
    assert candidates[0].text.startswith(
        "All JSON objects returned by an API MUST have the following fields:",
    )
    assert "kind:" in candidates[0].text


def test_extract_keyword_candidates_does_not_merge_non_keyword_last_sentence_lead_in() -> None:
    document = """
## Section

Many simple resources are "subresources". When resources wish to expose alternative actions or views that are closely coupled to a single resource, they should do so using new sub-resources. Common subresources include:

* /status: Used to write just the status portion.
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 1
    assert candidates[0].kind == normative_audit.CandidateKind.PARAGRAPH_SENTENCE
    assert candidates[0].lead_in_span is None


def test_audit_normative_coverage_matches_candidate_to_constraint() -> None:
    candidates = (
        normative_audit.KeywordCandidate(
            source_span="1-1",
            section="Section",
            kind=normative_audit.CandidateKind.PARAGRAPH_SENTENCE,
            text="The PUT and POST verbs on objects MUST ignore the status values.",
        ),
    )
    constraints = (
        normative_constraint.NormativeConstraint(
            id="norm_001",
            source_path=Path("docs/source/api-conventions.md"),
            source_span="1-1",
            text="The PUT and POST verbs on objects MUST ignore the `status` values.",
            strength_signal=normative_constraint.NormativeSignal.MUST_UPPER,
            atomicizable=True,
            notes="",
        ),
    )

    audit_result = normative_audit.audit_normative_coverage(candidates, constraints)

    assert audit_result.total_candidates == 1
    assert audit_result.matched_candidates == 1
    assert audit_result.records[0].matched_normative_ids == ("norm_001",)


def test_infer_strength_signal_prefers_stronger_keyword() -> None:
    signal = normative_audit.infer_strength_signal(
        "Fields must be set, but readers should not assume the field is present.",
    )

    assert signal == normative_constraint.NormativeSignal.MUST


def test_materialize_keyword_normative_rules_assigns_ids_and_signal() -> None:
    candidates = (
        normative_audit.KeywordCandidate(
            source_span="10-10",
            section="Section",
            kind=normative_audit.CandidateKind.PARAGRAPH_SENTENCE,
            text="The standard REST verbs MUST return singular JSON objects.",
        ),
    )

    rules = normative_audit.materialize_keyword_normative_rules(
        candidates=candidates,
        source_path=Path("docs/source/api-conventions.md"),
    )

    assert rules[0].id == "kw_norm_001"
    assert rules[0].strength_signal == normative_constraint.NormativeSignal.MUST_UPPER


def test_extract_keyword_candidates_does_not_split_on_eg_abbreviation() -> None:
    document = """
## Section

Controllers must take care to consider how a `status` field will be handled in the case of interrupted control loops (e.g. controller crash and restart), and must act idempotently and consistently.
""".strip()

    candidates = normative_audit.extract_keyword_candidates(document)

    assert len(candidates) == 1
    assert "controller crash and restart" in candidates[0].text
