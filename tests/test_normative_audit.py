from pathlib import Path

import normative_audit
import normative_constraint
import pytest


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


def test_extract_sentence_selection_tasks_keeps_block_and_separates_main_from_context() -> None:
    document = """
## Section

Conditions are represented as a list. This collection should be treated as a map with a key of `type`. More details follow later.
""".strip()

    tasks = normative_audit.extract_sentence_selection_tasks(document)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.block_original == (
        "Conditions are represented as a list. "
        "This collection should be treated as a map with a key of `type`. "
        "More details follow later."
    )
    assert task.main_sentence.id == "s2"
    assert task.main_sentence.text == "This collection should be treated as a map with a key of `type`."
    assert [sentence.id for sentence in task.shared_context_sentences] == ["s1"]
    assert [sentence.id for sentence in task.context_sentences] == ["s3"]
    assert [sentence.text for sentence in task.context_sentences] == [
        "More details follow later.",
    ]


def test_extract_sentence_selection_artifacts_excludes_permissive_only_sentences_from_tasks() -> None:
    document = """
## Section

Objects may report multiple conditions. New fields should explicitly set either `+optional` or `+required`. Resource implementers can include short names.
""".strip()

    artifacts = normative_audit.extract_sentence_selection_artifacts(document)

    assert [task.main_sentence.text for task in artifacts.tasks] == [
        "New fields should explicitly set either `+optional` or `+required`.",
    ]
    assert [
        (record.sentence.text, record.selection_status, record.signal_tags) for record in artifacts.audit_records
    ] == [
        (
            "Objects may report multiple conditions.",
            normative_audit.SelectionStatus.EXCLUDED,
            (normative_audit.SignalTag.PERMISSIVE,),
        ),
        (
            "New fields should explicitly set either `+optional` or `+required`.",
            normative_audit.SelectionStatus.INCLUDED,
            (
                normative_audit.SignalTag.OBLIGATION,
                normative_audit.SignalTag.RECOMMENDATION,
                normative_audit.SignalTag.PERMISSIVE,
            ),
        ),
        (
            "Resource implementers can include short names.",
            normative_audit.SelectionStatus.EXCLUDED,
            (normative_audit.SignalTag.PERMISSIVE,),
        ),
    ]


def test_extract_sentence_selection_artifacts_includes_do_not_and_avoid_prohibitions() -> None:
    document = """
## Section

Do not use underscores. Avoid the deprecated FooController naming pattern. Fields that do not have an `omitempty` json tag default to zero. This exists to avoid ambiguity.
""".strip()

    artifacts = normative_audit.extract_sentence_selection_artifacts(document)

    assert [task.main_sentence.text for task in artifacts.tasks] == [
        "Do not use underscores.",
        "Avoid the deprecated FooController naming pattern.",
    ]
    assert [(record.selection_status, record.signal_tags) for record in artifacts.audit_records] == [
        (normative_audit.SelectionStatus.INCLUDED, (normative_audit.SignalTag.PROHIBITION,)),
        (
            normative_audit.SelectionStatus.INCLUDED,
            (normative_audit.SignalTag.PROHIBITION, normative_audit.SignalTag.DEPRECATION),
        ),
    ]


def test_extract_sentence_selection_artifacts_excludes_example_sentences_from_tasks() -> None:
    document = """
## Section

When asserting a requirement in the positive, use "must". Examples: "must be greater than 0", "must match regex '[a-z]+'". Words like "should" imply that the assertion is optional, and must be avoided.
""".strip()

    artifacts = normative_audit.extract_sentence_selection_artifacts(document)

    assert [task.main_sentence.text for task in artifacts.tasks] == [
        'When asserting a requirement in the positive, use "must".',
        'Words like "should" imply that the assertion is optional, and must be avoided.',
    ]
    assert [
        (record.sentence.text, record.selection_status, record.exclusion_reason) for record in artifacts.audit_records
    ] == [
        (
            'When asserting a requirement in the positive, use "must".',
            normative_audit.SelectionStatus.INCLUDED,
            None,
        ),
        (
            'Examples: "must be greater than 0", "must match regex \'[a-z]+\'".',
            normative_audit.SelectionStatus.EXCLUDED,
            "example_sentence",
        ),
        (
            'Words like "should" imply that the assertion is optional, and must be avoided.',
            normative_audit.SelectionStatus.INCLUDED,
            None,
        ),
    ]


def test_extract_sentence_selection_artifacts_excludes_error_codes_section_from_tasks() -> None:
    document = """
## Error codes

* Suggested client recovery behavior:
  * Do not retry. Fix the request.

## Error messages

When asserting a requirement in the positive, use "must".
""".strip()

    artifacts = normative_audit.extract_sentence_selection_artifacts(document)

    assert [task.main_sentence.text for task in artifacts.tasks] == [
        'When asserting a requirement in the positive, use "must".',
    ]
    assert [
        (record.section, record.sentence.text, record.selection_status, record.exclusion_reason)
        for record in artifacts.audit_records
    ] == [
        (
            "Error codes",
            "Do not retry.",
            normative_audit.SelectionStatus.EXCLUDED,
            "excluded_section",
        ),
        (
            "Error messages",
            'When asserting a requirement in the positive, use "must".',
            normative_audit.SelectionStatus.INCLUDED,
            None,
        ),
    ]


def test_extract_sentence_selection_tasks_limits_context_to_neighboring_main_sentence_boundaries() -> None:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. This avoids ambiguous client behavior. Older APIs sometimes relied on implicit optionality. New fields should explicitly set either `+optional` or `+required`. This is expected to become stricter in the future. Generated clients rely on this metadata. Validation must reject unset required fields. This protects clients from incomplete objects.
""".strip()

    tasks = normative_audit.extract_sentence_selection_tasks(document)

    assert len(tasks) == 3
    assert [task.main_sentence.id for task in tasks] == ["s2", "s5", "s8"]
    assert [sentence.id for sentence in tasks[0].shared_context_sentences] == ["s1"]
    assert [sentence.id for sentence in tasks[0].context_sentences] == ["s3", "s4"]
    assert [sentence.id for sentence in tasks[1].shared_context_sentences] == ["s1"]
    assert [sentence.id for sentence in tasks[1].context_sentences] == ["s3", "s4", "s6", "s7"]
    assert [sentence.id for sentence in tasks[2].shared_context_sentences] == ["s1"]
    assert [sentence.id for sentence in tasks[2].context_sentences] == ["s6", "s7", "s9"]


def test_build_selected_original_always_includes_main_sentence_in_source_order() -> None:
    document = """
## Section

Conditions are represented as a list. This collection should be treated as a map with a key of `type`. More details follow later.
""".strip()
    task = normative_audit.extract_sentence_selection_tasks(document)[0]

    original = normative_audit.build_selected_original(task, ("s3", "s1"))

    assert original == (
        "Conditions are represented as a list. "
        "This collection should be treated as a map with a key of `type`. "
        "More details follow later."
    )


def test_build_selected_original_rejects_unknown_context_sentence_ids() -> None:
    document = """
## Section

Conditions are represented as a list. This collection should be treated as a map with a key of `type`.
""".strip()
    task = normative_audit.extract_sentence_selection_tasks(document)[0]

    with pytest.raises(ValueError, match="Unknown context sentence IDs"):
        normative_audit.build_selected_original(task, ("s99",))


def test_save_sentence_selection_tasks_writes_codex_ready_json(tmp_path: Path) -> None:
    document = """
## Section

Conditions are represented as a list. This collection should be treated as a map with a key of `type`.
""".strip()
    output_path = tmp_path / "tasks.json"

    normative_audit.save_sentence_selection_tasks(
        normative_audit.extract_sentence_selection_tasks(document),
        output_path,
    )

    assert output_path.read_text(encoding="utf-8").startswith('{\n  "tasks": [\n')
    assert (
        '"block_original": "Conditions are represented as a list. This collection should be treated as a map with a key of `type`."'
        in output_path.read_text(encoding="utf-8")
    )


def test_save_sentence_selection_audit_writes_inclusion_summary_and_records(tmp_path: Path) -> None:
    document = """
## Section

Objects may report multiple conditions. Fields must be set.
""".strip()
    artifacts = normative_audit.extract_sentence_selection_artifacts(document)
    output_path = tmp_path / "audit.json"

    normative_audit.save_sentence_selection_audit(artifacts.audit_records, output_path)

    saved = output_path.read_text(encoding="utf-8")
    assert '"included": 1' in saved
    assert '"excluded": 1' in saved
    assert '"exclusion_reason": "permissive_only"' in saved


def test_find_context_selection_conflicts_flags_non_shared_context_selected_by_multiple_tasks() -> None:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. This avoids ambiguous client behavior. New fields should explicitly set either `+optional` or `+required`.
""".strip()
    tasks = normative_audit.extract_sentence_selection_tasks(document)

    conflicts = normative_audit.find_context_selection_conflicts(
        tasks,
        {
            tasks[0].id: ("s3",),
            tasks[1].id: ("s3",),
        },
    )

    assert len(conflicts) == 1
    assert conflicts[0].sentence_id == "s3"
    assert conflicts[0].sentence_text == "This avoids ambiguous client behavior."
    assert conflicts[0].task_ids == (tasks[0].id, tasks[1].id)


def test_find_context_selection_conflicts_allows_shared_intro_selected_by_multiple_tasks() -> None:
    document = """
## Section

Optionality affects API compatibility. Fields must be either optional or required. This avoids ambiguous client behavior. New fields should explicitly set either `+optional` or `+required`.
""".strip()
    tasks = normative_audit.extract_sentence_selection_tasks(document)

    conflicts = normative_audit.find_context_selection_conflicts(
        tasks,
        {
            tasks[0].id: ("s1",),
            tasks[1].id: ("s1",),
        },
    )

    assert conflicts == ()
