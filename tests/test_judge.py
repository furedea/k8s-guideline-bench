"""Tests for LLM-as-a-Judge evaluator."""

import json
import logging
import subprocess
import threading
from pathlib import Path

import atomic_constraint
import claude_cli_client
import client_spec
import dataset_builder
import judge
import pr_collection
import pytest
from pytest_mock import MockerFixture


def _client_spec() -> client_spec.ClientSpec:
    return client_spec.ClientSpec(
        client_type=client_spec.ClientType.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
    )


def _judge_config_from_raw(document: dict[str, object]) -> judge.JudgeConfig:
    return judge.JudgeConfig.model_validate(document)


def _constraint() -> atomic_constraint.AtomicConstraint:
    return atomic_constraint.AtomicConstraint(
        id="atom_001",
        normative_source_ids=("norm_014",),
        source_path=Path("docs/source/api-conventions.md"),
        source_span="219-219",
        title="Kind field",
        rule="All JSON objects include a kind field.",
        rationale="Consistency",
        judgeability=atomic_constraint.Judgeability.MACHINE_CHECKABLE,
    )


def _constraint_with_id(constraint_id: str) -> atomic_constraint.AtomicConstraint:
    return atomic_constraint.AtomicConstraint(
        id=constraint_id,
        normative_source_ids=("norm_014",),
        source_path=Path("docs/source/api-conventions.md"),
        source_span="219-219",
        title="Kind field",
        rule="All JSON objects include a kind field.",
        rationale="Consistency",
        judgeability=atomic_constraint.Judgeability.LLM_CHECKABLE,
    )


def _instance(tmp_path: Path) -> dataset_builder.DatasetInstance:
    detail = pr_collection.PullRequestDetail(
        pr_number=42,
        base_sha="def456",
        head_sha="abc123",
        title="Rename field",
        body="",
        labels=("kind/cleanup",),
        merged_at="2026-03-01T00:00:00Z",
        changed_files=("api/foo.go",),
        added_lines=1,
        deleted_lines=0,
    )
    return dataset_builder.DatasetInstance(detail=detail, root=tmp_path)


def test_build_judge_prompt_includes_rule_and_patches(tmp_path: Path) -> None:
    prompt = judge.build_judge_prompt(
        instance=_instance(tmp_path),
        constraint=_constraint(),
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
    )

    assert "atom_001" in prompt
    assert "All JSON objects include a kind field." in prompt
    assert "Consistency" in prompt
    assert "machine_checkable" in prompt
    assert "api/foo.go" in prompt
    assert "diff --git a/api/foo.go" in prompt
    assert "+field" in prompt
    assert "+gold" in prompt
    assert "#42" in prompt
    assert "patch_effect=applied_by_patch" in prompt


def test_build_judge_prompt_omits_gold_patch_in_patch_only_mode(tmp_path: Path) -> None:
    prompt = judge.build_judge_prompt(
        instance=_instance(tmp_path),
        constraint=_constraint(),
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        mode=judge.JudgeMode.PATCH_ONLY,
    )

    assert "+field" in prompt
    assert "+gold" not in prompt
    assert "Gold patch" not in prompt
    assert "complies with the listed atomic constraint" in prompt


def test_judge_config_defaults_to_reference_based_mode() -> None:
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
    )

    assert config.judge_mode == judge.JudgeMode.REFERENCE_BASED


def test_judge_config_accepts_patch_only_mode_string() -> None:
    config = _judge_config_from_raw(
        {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "system_prompt": "judge",
            "client": _client_spec().model_dump(mode="json"),
            "judge_mode": "patch_only",
        },
    )

    assert config.judge_mode == judge.JudgeMode.PATCH_ONLY


def test_parse_judge_response_extracts_structured_verdict() -> None:
    response = (
        "Some preface.\n"
        '```json\n{"verdict": "compliant", "confidence": 0.92, '
        '"patch_effect": "applied_by_patch", "rationale": "Field added correctly."}\n```'
    )

    judgment = judge.parse_judge_response(response, constraint_id="atom_001")

    assert judgment == judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.92,
        rationale="Field added correctly.",
        patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
    )


def test_parse_judge_response_supports_bare_json_without_fence() -> None:
    response = (
        '{"verdict": "violated", "patch_effect": "not_relevant", '
        '"confidence": 0.3, "rationale": "Missing kind field."}'
    )

    judgment = judge.parse_judge_response(response, constraint_id="atom_001")

    assert judgment.verdict == judge.JudgeVerdict.VIOLATED
    assert judgment.patch_effect == judge.PatchEffect.NOT_APPLICABLE
    assert judgment.rationale == "Missing kind field."


def test_parse_judge_response_normalizes_not_relevant_to_not_applicable() -> None:
    response = '{"verdict": "violated", "patch_effect": "not_relevant", "confidence": 0.5, "rationale": ""}'

    judgment = judge.parse_judge_response(response, constraint_id="atom_001")

    assert judgment.patch_effect == judge.PatchEffect.NOT_APPLICABLE


def test_parse_judge_response_forces_compliant_with_unknown_patch_effect_when_not_applicable_provided() -> None:
    response = (
        '{"verdict": "compliant", "patch_effect": "not_applicable", '
        '"confidence": 0.6, "rationale": "compliant but effect unclear"}'
    )

    judgment = judge.parse_judge_response(response, constraint_id="atom_001")

    assert judgment.verdict == judge.JudgeVerdict.COMPLIANT
    assert judgment.patch_effect == judge.PatchEffect.UNKNOWN


def test_parse_judge_response_rejects_reserved_not_judged_verdict() -> None:
    response = '{"verdict": "not_judged", "confidence": 0.0, "rationale": ""}'

    judgment = judge.parse_judge_response(response, constraint_id="atom_001")

    assert judgment.status == judge.JudgmentStatus.PARSE_FAILURE
    assert judgment.verdict == judge.JudgeVerdict.NOT_JUDGED
    assert judgment.patch_effect == judge.PatchEffect.NOT_JUDGED


def test_failure_judgment_uses_not_judged_placeholders_for_verdict_and_patch_effect() -> None:
    judgment = judge._failure_judgment(  # type: ignore[attr-defined]
        "atom_001",
        judge.JudgmentStatus.API_FAILURE,
        "boom",
    )

    assert judgment.verdict == judge.JudgeVerdict.NOT_JUDGED
    assert judgment.patch_effect == judge.PatchEffect.NOT_JUDGED
    assert judgment.confidence == 0.0
    assert judgment.rationale == "boom"


def test_constraint_judgment_normalizes_legacy_failure_with_not_applicable_verdict() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        status=judge.JudgmentStatus.PARSE_FAILURE,
        verdict=judge.JudgeVerdict.NOT_APPLICABLE,
        confidence=0.4,
        rationale="legacy",
    )

    assert judgment.verdict == judge.JudgeVerdict.NOT_JUDGED
    assert judgment.patch_effect == judge.PatchEffect.NOT_JUDGED
    assert judgment.confidence == 0.0


def test_constraint_judgment_violated_forces_patch_effect_to_not_applicable() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.VIOLATED,
        rationale="rule broken",
    )

    assert judgment.patch_effect == judge.PatchEffect.NOT_APPLICABLE


def test_constraint_judgment_field_dump_order_starts_with_constraint_id_and_status() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="ok",
        patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
    )

    keys = tuple(judgment.model_dump(mode="json").keys())

    assert keys == ("constraint_id", "status", "verdict", "patch_effect", "confidence", "rationale")


def test_parse_judge_response_defaults_patch_effect_to_unknown_for_old_responses() -> None:
    judgment = judge.parse_judge_response(
        '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}',
        constraint_id="atom_001",
    )

    assert judgment.patch_effect == judge.PatchEffect.UNKNOWN


def test_parse_judge_response_marks_status_ok_when_parsed() -> None:
    judgment = judge.parse_judge_response(
        '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}',
        constraint_id="atom_001",
    )

    assert judgment.status == judge.JudgmentStatus.OK


def test_parse_judge_response_marks_status_parse_failure_when_no_json() -> None:
    judgment = judge.parse_judge_response("no json here", constraint_id="atom_002")

    assert judgment.status == judge.JudgmentStatus.PARSE_FAILURE
    assert judgment.confidence == 0.0


def test_parse_judge_response_marks_status_parse_failure_for_unknown_verdict() -> None:
    judgment = judge.parse_judge_response(
        '{"verdict": "definitely-not-a-real-verdict", "confidence": 0.1, "rationale": "x"}',
        constraint_id="atom_003",
    )

    assert judgment.status == judge.JudgmentStatus.PARSE_FAILURE


def test_constraint_judgment_status_defaults_to_ok() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="c1",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=1.0,
        rationale="",
    )

    assert judgment.status == judge.JudgmentStatus.OK


def test_summarize_judgments_counts_parse_failures_separately() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="",
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.PARSE_FAILURE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.total == 2
    assert summary.compliant == 1
    assert summary.parse_failure == 1
    assert summary.not_applicable == 0


def test_judge_instance_collects_judgments_and_persists_result(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    constraints = (_constraint(),)

    class StubClient:
        last_user_prompt = ""

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, model, max_tokens
            StubClient.last_user_prompt = user
            return '```json\n{"verdict": "compliant", "confidence": 0.8, "rationale": "ok"}\n```'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="You are a guideline compliance judge.",
        client=_client_spec(),
    )
    results_root = tmp_path / "results"

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    assert result.instance_id == "42"
    assert result.judgments[0].verdict == judge.JudgeVerdict.COMPLIANT
    assert "+gold" in StubClient.last_user_prompt
    output_path = results_root / "run-001" / "42" / "judgments.json"
    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["judgments"][0]["verdict"] == "compliant"


def test_judge_instance_evaluates_constraints_concurrently_when_max_workers_allows_it(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    constraints = (
        _constraint_with_id("atom_001"),
        _constraint_with_id("atom_002"),
    )
    both_calls_started = threading.Barrier(parties=2, timeout=1.0)
    seen_constraint_ids: list[str] = []
    seen_constraint_ids_lock = threading.Lock()

    class ConcurrentClient:
        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, model, max_tokens
            constraint_id = _constraint_id_from_prompt(user)
            with seen_constraint_ids_lock:
                seen_constraint_ids.append(constraint_id)
            both_calls_started.wait()
            return f'{{"verdict": "compliant", "confidence": 0.7, "rationale": "judged {constraint_id}"}}'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        max_workers=2,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=ConcurrentClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert sorted(seen_constraint_ids) == ["atom_001", "atom_002"]
    assert {judgment.rationale for judgment in result.judgments} == {
        "judged atom_001",
        "judged atom_002",
    }


def _constraint_id_from_prompt(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("- id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("Prompt did not include a constraint id.")


class _CountingStubClient:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        _ = system, user, model, max_tokens
        self.call_count += 1
        return '{"verdict": "compliant", "confidence": 0.7, "rationale": "ok"}'


def _stub_client_with_counter() -> _CountingStubClient:
    return _CountingStubClient()


def test_judge_instance_skip_existing_returns_existing_judgments_without_calling_client(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    constraints = (_constraint(),)
    results_root = tmp_path / "results"
    output_dir = results_root / "run-001" / "42"
    output_dir.mkdir(parents=True)
    preexisting = judge.InstanceJudgment(
        instance_id="42",
        run_id="run-001",
        judgments=(
            judge.ConstraintJudgment(
                constraint_id="atom_001",
                verdict=judge.JudgeVerdict.VIOLATED,
                confidence=0.9,
                rationale="cached",
            ),
        ),
    )
    _ = (output_dir / "judgments.json").write_text(
        json.dumps(preexisting.model_dump(mode="json")),
        encoding="utf-8",
    )
    stub_client = _stub_client_with_counter()
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        skip_existing=True,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="",
        gold_patch="",
        constraints=constraints,
        client=stub_client,
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    assert stub_client.call_count == 0
    assert result.judgments[0].verdict == judge.JudgeVerdict.VIOLATED
    assert result.judgments[0].rationale == "cached"


def test_judge_instance_skip_existing_reruns_non_ok_constraints_and_keeps_ok(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    constraints = (
        _constraint_with_id("atom_001"),
        _constraint_with_id("atom_002"),
    )
    results_root = tmp_path / "results"
    output_dir = results_root / "run-001" / "42"
    output_dir.mkdir(parents=True)
    preexisting = judge.InstanceJudgment(
        instance_id="42",
        run_id="run-001",
        judgments=(
            judge.ConstraintJudgment(
                constraint_id="atom_001",
                verdict=judge.JudgeVerdict.COMPLIANT,
                confidence=0.9,
                rationale="cached-ok",
            ),
            judge.ConstraintJudgment(
                constraint_id="atom_002",
                status=judge.JudgmentStatus.API_FAILURE,
                confidence=0.0,
                rationale="prior api failure",
            ),
        ),
    )
    _ = (output_dir / "judgments.json").write_text(
        json.dumps(preexisting.model_dump(mode="json")),
        encoding="utf-8",
    )
    stub_client = _stub_client_with_counter()
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        skip_existing=True,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=stub_client,
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    assert stub_client.call_count == 1
    by_id = {j.constraint_id: j for j in result.judgments}
    assert by_id["atom_001"].rationale == "cached-ok"
    assert by_id["atom_002"].verdict == judge.JudgeVerdict.COMPLIANT
    assert by_id["atom_002"].rationale == "ok"


def test_judge_instance_skip_existing_consults_partial_checkpoint_for_ok_constraints(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    constraints = (
        _constraint_with_id("atom_001"),
        _constraint_with_id("atom_002"),
    )
    results_root = tmp_path / "results"
    output_dir = results_root / "run-001" / "42"
    output_dir.mkdir(parents=True)
    partial_payload = {
        "judgments": [
            judge.ConstraintJudgment(
                constraint_id="atom_001",
                verdict=judge.JudgeVerdict.VIOLATED,
                confidence=0.5,
                rationale="from-partial",
            ).model_dump(mode="json"),
        ],
    }
    _ = (output_dir / "judgments.partial.json").write_text(
        json.dumps(partial_payload),
        encoding="utf-8",
    )
    stub_client = _stub_client_with_counter()
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        skip_existing=True,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=stub_client,
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    assert stub_client.call_count == 1
    by_id = {j.constraint_id: j for j in result.judgments}
    assert by_id["atom_001"].rationale == "from-partial"
    assert by_id["atom_002"].verdict == judge.JudgeVerdict.COMPLIANT


def test_judge_instance_propagates_claude_cli_fatal_error_and_keeps_completed_partial(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    instance = _instance(tmp_path)
    constraints = (
        _constraint_with_id("atom_001"),
        _constraint_with_id("atom_002"),
    )
    completed_first = threading.Event()

    class FatalAfterFirstClient:
        call_count = 0
        call_lock = threading.Lock()

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, model, max_tokens
            constraint_id = _constraint_id_from_prompt(user)
            with FatalAfterFirstClient.call_lock:
                FatalAfterFirstClient.call_count += 1
                count = FatalAfterFirstClient.call_count
            if count == 1:
                completed_first.set()
                return f'{{"verdict": "compliant", "confidence": 0.7, "rationale": "ok-{constraint_id}"}}'
            assert completed_first.wait(timeout=1.0)
            raise claude_cli_client.ClaudeCliFatalError(
                returncode=2,
                stdout="partial",
                stderr="auth required",
            )

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        max_workers=1,
    )
    results_root = tmp_path / "results"

    with caplog.at_level(logging.ERROR), pytest.raises(claude_cli_client.ClaudeCliFatalError) as exc_info:
        _ = judge.judge_instance(
            instance=instance,
            predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
            gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
            constraints=constraints,
            client=FatalAfterFirstClient(),
            config=config,
            run_id="run-001",
            results_root=results_root,
        )

    assert exc_info.value.returncode == 2
    instance_dir = results_root / "run-001" / "42"
    partial_path = instance_dir / "judgments.partial.json"
    partial = json.loads(partial_path.read_text(encoding="utf-8"))
    assert [j["constraint_id"] for j in partial["judgments"]] == ["atom_001"]
    assert partial["judgments"][0]["status"] == "ok"
    assert not (instance_dir / "judgments.json").exists()
    error_log = (instance_dir / "judge_errors.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(error_log) == 1
    error_record = json.loads(error_log[0])
    assert error_record["constraint_id"] == "atom_002"
    assert error_record["returncode"] == 2
    assert error_record["instance_id"] == "42"
    assert error_record["run_id"] == "run-001"
    assert "auth required" in error_record["stderr"]
    assert all("predicted" not in record.message for record in caplog.records)


def test_judge_instance_does_not_retry_claude_cli_fatal_error(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    constraints = (_constraint_with_id("atom_001"),)

    class AlwaysFatalClient:
        call_count = 0

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            AlwaysFatalClient.call_count += 1
            raise claude_cli_client.ClaudeCliFatalError(returncode=2, stdout="", stderr="boom")

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        max_retries=3,
    )

    with pytest.raises(claude_cli_client.ClaudeCliFatalError):
        _ = judge.judge_instance(
            instance=instance,
            predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
            gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
            constraints=constraints,
            client=AlwaysFatalClient(),
            config=config,
            run_id="run-001",
            results_root=tmp_path / "results",
        )

    assert AlwaysFatalClient.call_count == 1


def test_judge_instance_writes_partial_checkpoint_after_each_ok_constraint(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    constraints = (
        _constraint_with_id("atom_001"),
        _constraint_with_id("atom_002"),
    )
    seen_partial_sizes: list[int] = []
    seen_partial_lock = threading.Lock()
    partial_path = tmp_path / "results" / "run-001" / "42" / "judgments.partial.json"

    def record_partial_size() -> None:
        try:
            document = json.loads(partial_path.read_text(encoding="utf-8"))
            with seen_partial_lock:
                seen_partial_sizes.append(len(document["judgments"]))
        except FileNotFoundError:
            with seen_partial_lock:
                seen_partial_sizes.append(0)

    class ObservingClient:
        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, model, max_tokens
            constraint_id = _constraint_id_from_prompt(user)
            record_partial_size()
            return f'{{"verdict": "compliant", "confidence": 0.7, "rationale": "judged {constraint_id}"}}'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        max_workers=1,
    )

    _ = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=ObservingClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert seen_partial_sizes == [0, 1]


def test_judge_instance_skip_existing_false_overwrites_existing_judgments(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    constraints = (_constraint(),)
    results_root = tmp_path / "results"
    output_dir = results_root / "run-001" / "42"
    output_dir.mkdir(parents=True)
    _ = (output_dir / "judgments.json").write_text("stale", encoding="utf-8")
    stub_client = _stub_client_with_counter()
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        skip_existing=False,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=stub_client,
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    assert stub_client.call_count == 1
    assert result.judgments[0].verdict == judge.JudgeVerdict.COMPLIANT


def _write_base_file(instance_root: Path, relative: str, content: str) -> None:
    target = instance_root / "base" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_text(content, encoding="utf-8")


_PATCH_APPLIES = "diff --git a/foo.txt b/foo.txt\n--- a/foo.txt\n+++ b/foo.txt\n@@ -1 +1,2 @@\n line1\n+line2\n"

_PATCH_FAILS = "diff --git a/foo.txt b/foo.txt\n--- a/foo.txt\n+++ b/foo.txt\n@@ -1 +1,2 @@\n unrelated\n+line2\n"


def test_judge_config_default_patch_verification_is_none() -> None:
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
    )

    assert config.patch_verification == judge.PatchVerification.NONE


def test_judge_instance_with_apply_verification_proceeds_when_patch_applies(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    _write_base_file(instance.root, "foo.txt", "line1\n")
    constraints = (_constraint(),)

    class StubClient:
        call_count = 0

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            StubClient.call_count += 1
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = _judge_config_from_raw(
        {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "system_prompt": "judge",
            "client": _client_spec().model_dump(mode="json"),
            "patch_verification": "apply",
        },
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch=_PATCH_APPLIES,
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert StubClient.call_count == 1
    assert result.judgments[0].status == judge.JudgmentStatus.OK


def test_judge_instance_with_apply_verification_skips_llm_when_patch_fails(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    _write_base_file(instance.root, "foo.txt", "line1\n")
    constraints = (_constraint(),)

    class StubClient:
        call_count = 0

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            StubClient.call_count += 1
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        patch_verification=judge.PatchVerification.APPLY,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch=_PATCH_FAILS,
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert StubClient.call_count == 0
    assert result.judgments[0].status == judge.JudgmentStatus.PATCH_APPLY_FAILURE


def _instance_with_go_base(tmp_path: Path) -> dataset_builder.DatasetInstance:
    instance = _instance(tmp_path)
    _write_base_file(instance.root, "foo.txt", "line1\n")
    return instance


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=b"", stderr=stderr.encode())


def test_judge_instance_with_build_verification_proceeds_when_build_passes(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance = _instance_with_go_base(tmp_path)
    constraints = (_constraint(),)
    run_step = mocker.patch("judge._run_go_step", autospec=True, return_value=None)

    class StubClient:
        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = _judge_config_from_raw(
        {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "system_prompt": "judge",
            "client": _client_spec().model_dump(mode="json"),
            "patch_verification": "build",
        },
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch=_PATCH_APPLIES,
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert result.judgments[0].status == judge.JudgmentStatus.OK
    assert [call.args[0] for call in run_step.call_args_list] == ["build"]


def test_judge_instance_with_build_verification_marks_build_failure_when_build_errors(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance = _instance_with_go_base(tmp_path)
    constraints = (_constraint(),)
    _ = mocker.patch(
        "judge._run_go_step",
        autospec=True,
        return_value=judge.VerificationFailure(
            status=judge.JudgmentStatus.BUILD_FAILURE,
            rationale="undefined: foo",
        ),
    )

    class StubClient:
        call_count = 0

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            StubClient.call_count += 1
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        patch_verification=judge.PatchVerification.BUILD,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch=_PATCH_APPLIES,
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert StubClient.call_count == 0
    assert result.judgments[0].status == judge.JudgmentStatus.BUILD_FAILURE
    assert "undefined: foo" in result.judgments[0].rationale


def test_judge_instance_with_test_verification_marks_test_failure_when_tests_fail(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instance = _instance_with_go_base(tmp_path)
    constraints = (_constraint(),)

    def fake_step(
        subcommand: str,
        *,
        workdir: Path,
        packages: tuple[str, ...],
        timeout: float,
    ) -> judge.VerificationFailure | None:
        _ = workdir, packages, timeout
        if subcommand == "test":
            return judge.VerificationFailure(
                status=judge.JudgmentStatus.TEST_FAILURE,
                rationale="--- FAIL: TestFoo",
            )
        return None

    _ = mocker.patch("judge._run_go_step", autospec=True, side_effect=fake_step)

    class StubClient:
        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = _judge_config_from_raw(
        {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "system_prompt": "judge",
            "client": _client_spec().model_dump(mode="json"),
            "patch_verification": "test",
        },
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch=_PATCH_APPLIES,
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert result.judgments[0].status == judge.JudgmentStatus.TEST_FAILURE


def test_run_go_step_returns_failure_on_subprocess_error(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    _ = mocker.patch(
        "subprocess.run",
        autospec=True,
        return_value=_completed(returncode=2, stderr="syntax error"),
    )

    failure = judge._run_go_step(  # type: ignore[attr-defined]
        "build",
        workdir=tmp_path,
        packages=("./api/...",),
        timeout=60.0,
    )

    assert failure is not None
    assert failure.status == judge.JudgmentStatus.BUILD_FAILURE
    assert "syntax error" in failure.rationale


def test_run_go_step_returns_none_when_no_packages() -> None:
    failure = judge._run_go_step(  # type: ignore[attr-defined]
        "build",
        workdir=Path("/nonexistent"),
        packages=(),
        timeout=60.0,
    )

    assert failure is None


def test_run_go_step_marks_build_failure_on_timeout(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    _ = mocker.patch(
        "subprocess.run",
        autospec=True,
        side_effect=subprocess.TimeoutExpired(cmd=["go", "build"], timeout=1.0),
    )

    failure = judge._run_go_step(  # type: ignore[attr-defined]
        "build",
        workdir=tmp_path,
        packages=("./api/...",),
        timeout=1.0,
    )

    assert failure is not None
    assert failure.status == judge.JudgmentStatus.BUILD_FAILURE
    assert "timed out" in failure.rationale.lower()


def test_summarize_judgments_counts_build_and_test_failures_separately() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.BUILD_FAILURE,
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.TEST_FAILURE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.build_failure == 1
    assert summary.test_failure == 1


def test_compliance_rate_uses_compliant_over_compliant_plus_violated() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="",
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=1.0,
                    rationale="",
                ),
                judge.ConstraintJudgment(
                    constraint_id="c3",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.PARSE_FAILURE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.compliance_rate == 1.0
    assert summary.effective_total == 1


def test_newly_satisfied_rate_counts_only_constraints_applied_by_patch() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="changed by patch",
                    patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="already true before the patch",
                    patch_effect=judge.PatchEffect.ALREADY_SATISFIED,
                ),
                judge.ConstraintJudgment(
                    constraint_id="c3",
                    verdict=judge.JudgeVerdict.VIOLATED,
                    confidence=1.0,
                    rationale="still violated",
                    patch_effect=judge.PatchEffect.NOT_APPLICABLE,
                ),
                judge.ConstraintJudgment(
                    constraint_id="c4",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=1.0,
                    rationale="outside scope",
                    patch_effect=judge.PatchEffect.NOT_APPLICABLE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.compliant == 2
    assert summary.newly_satisfied == 1
    assert summary.effective_total == 3
    assert summary.newly_satisfied_rate == 1 / 3


def test_compliance_rate_is_zero_when_no_applicable_judgments() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=1.0,
                    rationale="",
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.API_FAILURE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.compliance_rate == 0.0
    assert summary.effective_total == 0


def test_summarize_judgments_counts_patch_apply_failures_separately() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.PATCH_APPLY_FAILURE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.patch_apply_failure == 1
    assert summary.not_applicable == 0


def test_judge_config_default_target_selection_is_all_constraints() -> None:
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
    )

    assert config.judge_target_selection == judge.JudgeTargetSelection.ALL_CONSTRAINTS


def _machine_checkable_constraint() -> atomic_constraint.AtomicConstraint:
    return atomic_constraint.AtomicConstraint(
        id="atom_machine",
        normative_source_ids=("norm_001",),
        source_path=Path("docs/source/api-conventions.md"),
        source_span="10-10",
        title="Machine rule",
        rule="Use int32 instead of int.",
        rationale="",
        judgeability=atomic_constraint.Judgeability.MACHINE_CHECKABLE,
    )


def _llm_checkable_constraint() -> atomic_constraint.AtomicConstraint:
    return atomic_constraint.AtomicConstraint(
        id="atom_llm",
        normative_source_ids=("norm_002",),
        source_path=Path("docs/source/api-conventions.md"),
        source_span="20-20",
        title="LLM rule",
        rule="Spec fields use declarative names.",
        rationale="",
        judgeability=atomic_constraint.Judgeability.LLM_CHECKABLE,
    )


def test_judge_instance_writes_judge_targets_json_with_selected_constraint_ids(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    constraints = (_machine_checkable_constraint(), _llm_checkable_constraint())

    class StubClient:
        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
    )
    results_root = tmp_path / "results"

    _ = judge.judge_instance(
        instance=instance,
        predicted_patch="",
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    targets_path = results_root / "run-001" / "42" / "judge_targets.json"
    document = json.loads(targets_path.read_text(encoding="utf-8"))
    assert document["selection"] == "all_constraints"
    assert document["constraint_ids"] == ["atom_machine", "atom_llm"]


def test_judge_instance_llm_and_hybrid_selection_skips_machine_checkable(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    constraints = (_machine_checkable_constraint(), _llm_checkable_constraint())

    seen_constraint_ids: list[str] = []

    class StubClient:
        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, model, max_tokens
            for line in user.splitlines():
                if line.startswith("- id:"):
                    seen_constraint_ids.append(line.split(":", 1)[1].strip())
                    break
            return '{"verdict": "compliant", "confidence": 0.5, "rationale": "ok"}'

    config = _judge_config_from_raw(
        {
            "model": "claude-opus-4-7",
            "max_tokens": 1024,
            "system_prompt": "judge",
            "client": _client_spec().model_dump(mode="json"),
            "judge_target_selection": "llm_and_hybrid",
        },
    )
    results_root = tmp_path / "results"

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="",
        gold_patch="",
        constraints=constraints,
        client=StubClient(),
        config=config,
        run_id="run-001",
        results_root=results_root,
    )

    assert seen_constraint_ids == ["atom_llm"]
    assert tuple(j.constraint_id for j in result.judgments) == ("atom_llm",)
    document = json.loads((results_root / "run-001" / "42" / "judge_targets.json").read_text("utf-8"))
    assert document["constraint_ids"] == ["atom_llm"]


def test_judge_config_default_max_retries_is_zero() -> None:
    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
    )

    assert config.max_retries == 0


def test_judge_instance_retries_on_client_exception_then_succeeds(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    constraints = (_constraint(),)

    class FlakyClient:
        call_count = 0

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            FlakyClient.call_count += 1
            if FlakyClient.call_count == 1:
                raise RuntimeError("transient")
            return '{"verdict": "compliant", "confidence": 0.9, "rationale": "ok"}'

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        max_retries=2,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=FlakyClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert FlakyClient.call_count == 2
    assert result.judgments[0].status == judge.JudgmentStatus.OK
    assert result.judgments[0].verdict == judge.JudgeVerdict.COMPLIANT


def test_judge_instance_marks_api_failure_after_exhausting_retries(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    constraints = (_constraint(),)

    class AlwaysFailingClient:
        call_count = 0

        def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
            _ = system, user, model, max_tokens
            AlwaysFailingClient.call_count += 1
            raise RuntimeError("boom")

    config = judge.JudgeConfig(
        model="claude-opus-4-7",
        max_tokens=1024,
        system_prompt="judge",
        client=_client_spec(),
        max_retries=2,
    )

    result = judge.judge_instance(
        instance=instance,
        predicted_patch="diff --git a/api/foo.go b/api/foo.go\n+field\n",
        gold_patch="diff --git a/api/foo.go b/api/foo.go\n+gold\n",
        constraints=constraints,
        client=AlwaysFailingClient(),
        config=config,
        run_id="run-001",
        results_root=tmp_path / "results",
    )

    assert AlwaysFailingClient.call_count == 3
    assert result.judgments[0].status == judge.JudgmentStatus.API_FAILURE
    assert "boom" in result.judgments[0].rationale


def test_summarize_judgments_counts_api_failures_separately() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="",
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.NOT_APPLICABLE,
                    confidence=0.0,
                    rationale="",
                    status=judge.JudgmentStatus.API_FAILURE,
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.compliant == 1
    assert summary.not_applicable == 0
    assert summary.api_failure == 1


def test_summarize_judgments_aggregates_counts_by_verdict() -> None:
    results = (
        judge.InstanceJudgment(
            instance_id="1",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="",
                ),
                judge.ConstraintJudgment(
                    constraint_id="c2",
                    verdict=judge.JudgeVerdict.VIOLATED,
                    confidence=1.0,
                    rationale="",
                ),
            ),
        ),
        judge.InstanceJudgment(
            instance_id="2",
            run_id="run",
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="c1",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=1.0,
                    rationale="",
                ),
            ),
        ),
    )

    summary = judge.summarize_judgments(results)

    assert summary.total == 3
    assert summary.compliant == 2
    assert summary.violated == 1
    assert summary.not_applicable == 0
    assert summary.compliance_rate == 2 / 3
