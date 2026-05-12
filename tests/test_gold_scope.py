"""Tests for gold-scope judgment orchestration."""

import json
from pathlib import Path
from typing import cast

import atomic_constraint
import client_spec
import completion_client
import dataset_builder
import gold_scope
import judge
import pr_collection
from pytest_mock import MockerFixture


def _client_spec() -> client_spec.ClientSpec:
    return client_spec.ClientSpec(
        client_type=client_spec.ClientType.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
    )


def _constraint(constraint_id: str) -> atomic_constraint.AtomicConstraint:
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


def _instance(tmp_path: Path, pr_number: int) -> dataset_builder.DatasetInstance:
    detail = pr_collection.PullRequestDetail(
        pr_number=pr_number,
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
    return dataset_builder.DatasetInstance(detail=detail, root=tmp_path / str(pr_number))


def _gold_scope_config() -> judge.JudgeConfig:
    return judge.JudgeConfig(
        model="sonnet",
        max_tokens=256,
        system_prompt="gold judge",
        client=_client_spec(),
        judge_mode=judge.JudgeMode.PATCH_ONLY,
    )


class _StubClient:
    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        _ = system, user, model, max_tokens
        return ""


def test_gold_scope_run_id_is_gold_scope() -> None:
    assert gold_scope.GOLD_SCOPE_RUN_ID == "gold_scope"


def test_judge_gold_scope_calls_judge_instance_with_patch_only_inputs(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instances = (_instance(tmp_path, 42),)
    gold_patches = ("diff --git a/api/foo.go b/api/foo.go\n+kind: Field\n",)
    constraints = (_constraint("atom_001"),)
    config = _gold_scope_config()
    results_root = tmp_path / "results"
    expected = judge.InstanceJudgment(
        instance_id="42",
        run_id="gold_scope",
        judgments=(
            judge.ConstraintJudgment(
                constraint_id="atom_001",
                verdict=judge.JudgeVerdict.COMPLIANT,
                confidence=0.9,
                rationale="ok",
                patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
            ),
        ),
    )
    judge_spy = mocker.patch("judge.judge_instance", autospec=True, return_value=expected)
    stub_client = _StubClient()

    results = gold_scope.judge_gold_scope(
        instances=instances,
        gold_patches=gold_patches,
        constraints=constraints,
        client=cast("completion_client.CompletionClient", stub_client),
        config=config,
        results_root=results_root,
    )

    assert judge_spy.call_count == 1
    call_kwargs = judge_spy.call_args.kwargs
    assert call_kwargs["instance"] is instances[0]
    assert call_kwargs["predicted_patch"] == gold_patches[0]
    assert call_kwargs["gold_patch"] == ""
    assert call_kwargs["run_id"] == "gold_scope"
    assert call_kwargs["constraints"] == constraints
    assert call_kwargs["client"] is stub_client
    assert call_kwargs["config"] is config
    assert call_kwargs["results_root"] == results_root
    assert results == (expected,)


def test_judge_gold_scope_iterates_every_instance_with_paired_gold_patch(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    instances = (_instance(tmp_path, 42), _instance(tmp_path, 43))
    gold_patches = ("diff-42\n", "diff-43\n")
    constraints = (_constraint("atom_001"),)
    config = _gold_scope_config()

    def fake_judge_instance(
        *,
        instance: dataset_builder.DatasetInstance,
        predicted_patch: str,
        run_id: str,
        **_: object,
    ) -> judge.InstanceJudgment:
        return judge.InstanceJudgment(
            instance_id=str(instance.detail.pr_number),
            run_id=run_id,
            judgments=(
                judge.ConstraintJudgment(
                    constraint_id="atom_001",
                    verdict=judge.JudgeVerdict.COMPLIANT,
                    confidence=0.9,
                    rationale=predicted_patch,
                    patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
                ),
            ),
        )

    _ = mocker.patch("judge.judge_instance", side_effect=fake_judge_instance)

    results = gold_scope.judge_gold_scope(
        instances=instances,
        gold_patches=gold_patches,
        constraints=constraints,
        client=cast("completion_client.CompletionClient", _StubClient()),
        config=config,
        results_root=tmp_path / "results",
    )

    assert tuple(result.instance_id for result in results) == ("42", "43")
    assert tuple(result.judgments[0].rationale for result in results) == ("diff-42\n", "diff-43\n")


def test_is_in_scope_returns_true_for_gold_applied_by_patch() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="ok",
        patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
    )

    assert gold_scope.is_in_scope(judgment) is True


def test_is_in_scope_returns_false_for_gold_violated() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.VIOLATED,
        confidence=0.7,
        rationale="bad",
    )

    assert gold_scope.is_in_scope(judgment) is False


def test_is_in_scope_returns_false_for_already_satisfied_gold_compliance() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="already satisfied before the patch",
        patch_effect=judge.PatchEffect.ALREADY_SATISFIED,
    )

    assert gold_scope.is_in_scope(judgment) is False


def test_is_in_scope_returns_false_for_not_applicable() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.NOT_APPLICABLE,
        confidence=0.3,
        rationale="oob",
    )

    assert gold_scope.is_in_scope(judgment) is False


def test_is_in_scope_returns_false_for_non_ok_status() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        status=judge.JudgmentStatus.API_FAILURE,
        verdict=judge.JudgeVerdict.NOT_APPLICABLE,
        confidence=0.0,
        rationale="boom",
    )

    assert gold_scope.is_in_scope(judgment) is False


def test_load_gold_scope_returns_in_scope_constraint_ids_per_instance(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    gold_dir = results_root / "gold_scope" / "42"
    gold_dir.mkdir(parents=True)
    _ = (gold_dir / "judgments.json").write_text(
        json.dumps(
            {
                "instance_id": "42",
                "run_id": "gold_scope",
                "judgments": [
                    {
                        "constraint_id": "atom_001",
                        "status": "ok",
                        "verdict": "compliant",
                        "patch_effect": "applied_by_patch",
                        "confidence": 0.9,
                        "rationale": "",
                    },
                    {
                        "constraint_id": "atom_002",
                        "status": "ok",
                        "verdict": "not_applicable",
                        "patch_effect": "unknown",
                        "confidence": 0.5,
                        "rationale": "",
                    },
                    {
                        "constraint_id": "atom_003",
                        "status": "ok",
                        "verdict": "violated",
                        "patch_effect": "unknown",
                        "confidence": 0.6,
                        "rationale": "",
                    },
                    {
                        "constraint_id": "atom_004",
                        "status": "api_failure",
                        "verdict": "not_applicable",
                        "patch_effect": "unknown",
                        "confidence": 0.0,
                        "rationale": "",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    scope = gold_scope.load_gold_scope(results_root)

    assert scope == {"42": frozenset({"atom_001"})}


def test_load_gold_scope_aggregates_multiple_instances(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    for pr_id, in_scope_ids in (("42", ("atom_001",)), ("43", ("atom_002", "atom_003"))):
        instance_dir = results_root / "gold_scope" / pr_id
        instance_dir.mkdir(parents=True)
        _ = (instance_dir / "judgments.json").write_text(
            json.dumps(
                {
                    "instance_id": pr_id,
                    "run_id": "gold_scope",
                    "judgments": [
                        {
                            "constraint_id": cid,
                            "status": "ok",
                            "verdict": "compliant",
                            "patch_effect": "applied_by_patch",
                            "confidence": 0.9,
                            "rationale": "",
                        }
                        for cid in in_scope_ids
                    ],
                },
            ),
            encoding="utf-8",
        )

    scope = gold_scope.load_gold_scope(results_root)

    assert scope == {
        "42": frozenset({"atom_001"}),
        "43": frozenset({"atom_002", "atom_003"}),
    }


def test_load_gold_scope_returns_empty_dict_when_no_gold_scope_directory(tmp_path: Path) -> None:
    assert gold_scope.load_gold_scope(tmp_path) == {}


def test_load_gold_scope_skips_instances_without_judgments_file(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    (results_root / "gold_scope" / "42").mkdir(parents=True)

    assert gold_scope.load_gold_scope(results_root) == {}


def test_is_existing_rule_returns_true_for_already_satisfied_gold_compliance() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="already satisfied",
        patch_effect=judge.PatchEffect.ALREADY_SATISFIED,
    )

    assert gold_scope.is_existing_rule(judgment) is True


def test_is_existing_rule_returns_false_for_applied_by_patch_gold_compliance() -> None:
    judgment = judge.ConstraintJudgment(
        constraint_id="atom_001",
        verdict=judge.JudgeVerdict.COMPLIANT,
        confidence=0.9,
        rationale="newly satisfied",
        patch_effect=judge.PatchEffect.APPLIED_BY_PATCH,
    )

    assert gold_scope.is_existing_rule(judgment) is False
