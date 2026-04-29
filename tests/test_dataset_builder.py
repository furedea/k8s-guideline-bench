"""Tests for dataset instance builder (PR-based flow)."""

import json
from pathlib import Path

import dataset_builder
import dataset_spec
import pr_collection
import verification
from pytest_mock import MockerFixture


def _make_detail(
    pr_number: int = 42,
    changed_files: tuple[str, ...] = ("api/foo.go", "api/bar.go"),
    added_lines: int = 20,
    deleted_lines: int = 10,
    labels: tuple[str, ...] = ("kind/cleanup",),
) -> pr_collection.PullRequestDetail:
    return pr_collection.PullRequestDetail(
        pr_number=pr_number,
        base_sha="def456",
        head_sha="abc123",
        title="Refactor foo",
        body="Detailed body.",
        labels=labels,
        merged_at="2026-03-01T00:00:00Z",
        changed_files=changed_files,
        added_lines=added_lines,
        deleted_lines=deleted_lines,
    )


def _make_spec(
    tmp_path: Path,
    **overrides: object,
) -> dataset_spec.DatasetSpec:
    defaults: dict[str, object] = {
        "github_repo": "kubernetes/kubernetes",
        "repo_path": Path("/tmp/k8s"),
        "target_paths": ("api",),
        "since": "2024-01-01",
        "pr_search_labels": ("kind/cleanup",),
        "datasets_root": tmp_path / "datasets",
    }
    defaults.update(overrides)
    return dataset_spec.DatasetSpec(**defaults)  # ty: ignore[invalid-argument-type]


def test_build_dataset_instance_writes_base_and_gold_files_and_task_metadata(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    detail = _make_detail()
    repo_path = Path("/tmp/kubernetes")
    datasets_root = tmp_path / "datasets"

    mock_show = mocker.patch("dataset_builder._git_show_file", autospec=True)
    mock_show.side_effect = lambda _repo, sha, path: f"{sha}:{path}\n".encode()
    mock_diff = mocker.patch(
        "dataset_builder._git_diff",
        autospec=True,
        return_value=b"diff --git a/api/foo.go b/api/foo.go\n",
    )

    instance = dataset_builder.build_dataset_instance(detail, repo_path, datasets_root)

    assert instance.root == datasets_root / "42"
    assert (datasets_root / "42" / "base" / "api" / "foo.go").read_text(encoding="utf-8") == ("def456:api/foo.go\n")
    assert (datasets_root / "42" / "gold" / "api" / "bar.go").read_text(encoding="utf-8") == ("abc123:api/bar.go\n")
    mock_diff.assert_called_once_with(
        repo_path,
        "def456",
        "abc123",
        ("api/foo.go", "api/bar.go"),
    )
    assert (datasets_root / "42" / "gold_patch.diff").read_text(encoding="utf-8") == (
        "diff --git a/api/foo.go b/api/foo.go\n"
    )

    task = json.loads((datasets_root / "42" / "task.json").read_text(encoding="utf-8"))
    assert task == {
        "pr_number": 42,
        "base_sha": "def456",
        "head_sha": "abc123",
        "title": "Refactor foo",
        "body": "Detailed body.",
        "labels": ["kind/cleanup"],
        "merged_at": "2026-03-01T00:00:00Z",
        "changed_files": ["api/foo.go", "api/bar.go"],
        "added_lines": 20,
        "deleted_lines": 10,
    }


def test_build_dataset_instance_rejects_empty_gold_patch(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    detail = _make_detail(pr_number=96657)
    repo_path = Path("/tmp/kubernetes")
    datasets_root = tmp_path / "datasets"
    _ = mocker.patch("dataset_builder._git_show_file", autospec=True, return_value=b"content\n")
    _ = mocker.patch("dataset_builder._git_diff", autospec=True, return_value=b"")

    try:
        dataset_builder.build_dataset_instance(detail, repo_path, datasets_root)
    except dataset_builder.EmptyGoldPatchError as error:
        assert error.pr_number == 96657

    assert not (datasets_root / "96657").exists()


def test_build_dataset_instance_skips_files_missing_from_base(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    detail = _make_detail()
    repo_path = Path("/tmp/kubernetes")
    datasets_root = tmp_path / "datasets"

    def fake_show(_repo: Path, sha: str, path: str) -> bytes:
        if sha == "def456" and path == "api/bar.go":
            raise dataset_builder.GitObjectMissingError(path=path, sha=sha)
        return f"{sha}:{path}\n".encode()

    _ = mocker.patch("dataset_builder._git_show_file", autospec=True, side_effect=fake_show)
    _ = mocker.patch("dataset_builder._git_diff", autospec=True, return_value=b"diff --git\n")

    _ = dataset_builder.build_dataset_instance(detail, repo_path, datasets_root)

    assert (datasets_root / "42" / "base" / "api" / "foo.go").exists()
    assert not (datasets_root / "42" / "base" / "api" / "bar.go").exists()
    assert (datasets_root / "42" / "gold" / "api" / "bar.go").exists()


def test_write_snapshots_preserves_non_utf8_file_bytes(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    detail = _make_detail(changed_files=("api/binary.dat",))
    repo_path = Path("/tmp/kubernetes")
    datasets_root = tmp_path / "datasets"
    non_utf8_content = b"\x80binary\n"
    _ = mocker.patch(
        "dataset_builder._git_show_file",
        autospec=True,
        return_value=non_utf8_content,
    )
    _ = mocker.patch("dataset_builder._git_diff", autospec=True, return_value=b"diff --git\n")

    _ = dataset_builder.build_dataset_instance(detail, repo_path, datasets_root)

    assert (datasets_root / "42" / "base" / "api" / "binary.dat").read_bytes() == non_utf8_content
    assert (datasets_root / "42" / "gold_patch.diff").read_bytes() == b"diff --git\n"


def test_build_dataset_from_spec_filters_labels_paths_exclusions_and_size(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    kept = _make_detail(
        pr_number=1,
        changed_files=("api/foo.go",),
        added_lines=20,
        deleted_lines=10,
        labels=("kind/cleanup",),
    )
    wrong_label = _make_detail(
        pr_number=2,
        changed_files=("api/foo.go",),
        labels=("kind/bug",),
    )
    outside_target = _make_detail(
        pr_number=3,
        changed_files=("docs/README.md",),
        labels=("kind/cleanup",),
    )
    generated_only = _make_detail(
        pr_number=4,
        changed_files=("api/zz_generated_deepcopy.go",),
        labels=("kind/cleanup",),
    )
    too_big = _make_detail(
        pr_number=5,
        changed_files=("api/huge.go",),
        added_lines=5000,
        deleted_lines=0,
        labels=("kind/cleanup",),
    )
    _ = mocker.patch(
        "pr_collection.collect_pull_requests",
        autospec=True,
        return_value=(kept, wrong_label, outside_target, generated_only, too_big),
    )
    _ = mocker.patch("dataset_builder._git_show_file", autospec=True, return_value=b"content\n")
    _ = mocker.patch("dataset_builder._git_diff", autospec=True, return_value=b"diff --git\n")

    spec = _make_spec(
        tmp_path,
        exclusion_patterns=("**/zz_generated_*.go",),
        required_pr_labels=("kind/cleanup",),
        excluded_pr_labels=("kind/bug",),
        max_changed_lines=500,
    )

    instances = dataset_builder.build_dataset_from_spec(spec)

    assert [instance.detail.pr_number for instance in instances] == [1]


def test_build_dataset_from_spec_drops_empty_gold_patch_instances(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    kept = _make_detail(pr_number=1)
    empty_patch = _make_detail(pr_number=2)
    _ = mocker.patch(
        "pr_collection.collect_pull_requests",
        autospec=True,
        return_value=(kept, empty_patch),
    )
    _ = mocker.patch("dataset_builder._git_show_file", autospec=True, return_value=b"content\n")
    diff = mocker.patch("dataset_builder._git_diff", autospec=True)
    diff.side_effect = [b"diff --git\n", b""]

    spec = _make_spec(tmp_path)

    instances = dataset_builder.build_dataset_from_spec(spec)

    assert [instance.detail.pr_number for instance in instances] == [1]
    assert (tmp_path / "datasets" / "1").exists()
    assert not (tmp_path / "datasets" / "2").exists()


def test_resolve_effective_since_uses_latest_cutoff_when_present() -> None:
    effective = dataset_builder.resolve_effective_since(
        "2024-01-01",
        {"claude-opus-4-7": "2026-01-01", "kimi-k2": "2025-06-15"},
    )
    assert effective == "2024-01-01"


def test_resolve_effective_since_keeps_fallback_when_no_cutoffs() -> None:
    assert dataset_builder.resolve_effective_since("2024-01-01", {}) == "2024-01-01"


def test_build_dataset_from_spec_ignores_model_cutoffs_for_effective_since(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    collect = mocker.patch(
        "pr_collection.collect_pull_requests",
        autospec=True,
        return_value=(),
    )

    spec = _make_spec(
        tmp_path,
        model_cutoffs={"opus": "2026-01-01", "kimi": "2025-06-15"},
    )

    _ = dataset_builder.build_dataset_from_spec(spec)

    collect.assert_called_once_with(
        github_repo=spec.github_repo,
        since="2024-01-01",
        search_labels=spec.pr_search_labels,
        cache_dir=spec.pr_cache_dir,
        limit=spec.pr_search_limit,
        until=spec.pr_search_until,
        window_days=spec.pr_search_window_days,
    )


def test_build_dataset_from_spec_rejects_instances_that_fail_go_build(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    passing = _make_detail(pr_number=11).model_copy(update={"head_sha": "good"})
    failing = _make_detail(pr_number=22).model_copy(update={"head_sha": "bad"})
    _ = mocker.patch(
        "pr_collection.collect_pull_requests",
        autospec=True,
        return_value=(passing, failing),
    )
    _ = mocker.patch("dataset_builder._git_show_file", autospec=True, return_value=b"content\n")
    _ = mocker.patch("dataset_builder._git_diff", autospec=True, return_value=b"diff --git\n")

    def fake_verify(
        *,
        sha: str,
        changed_files: tuple[str, ...],
        repo_path: Path,
        level: verification.VerificationLevel,
    ) -> verification.VerificationResult:
        del changed_files, repo_path
        return verification.VerificationResult(
            sha=sha,
            level=level,
            passed=sha == "good",
            error_excerpt="" if sha == "good" else "build failed",
        )

    _ = mocker.patch("verification.verify_instance", autospec=True, side_effect=fake_verify)

    rejected_root = tmp_path / "rejected"
    spec = _make_spec(
        tmp_path,
        verification_level=verification.VerificationLevel.BUILD,
        rejected_root=rejected_root,
    )

    instances = dataset_builder.build_dataset_from_spec(spec)

    assert [instance.detail.pr_number for instance in instances] == [11]
    assert not (tmp_path / "datasets" / "22").exists()
    assert (rejected_root / "22" / "verification_result.json").exists()
    rejection = json.loads(
        (rejected_root / "22" / "verification_result.json").read_text(encoding="utf-8"),
    )
    assert rejection["passed"] is False
    assert "build failed" in rejection["error_excerpt"]


def test_build_dataset_from_spec_applies_pr_limit_after_filters(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    details = tuple(
        _make_detail(
            pr_number=index,
            changed_files=("api/foo.go",) if index % 2 == 0 else ("api/zz_generated_x.go",),
        )
        for index in range(6)
    )
    _ = mocker.patch(
        "pr_collection.collect_pull_requests",
        autospec=True,
        return_value=details,
    )
    _ = mocker.patch("dataset_builder._git_show_file", autospec=True, return_value=b"content\n")
    _ = mocker.patch("dataset_builder._git_diff", autospec=True, return_value=b"diff --git\n")

    spec = _make_spec(
        tmp_path,
        exclusion_patterns=("**/zz_generated_*.go",),
        pr_limit=2,
    )

    instances = dataset_builder.build_dataset_from_spec(spec)

    assert [instance.detail.pr_number for instance in instances] == [0, 2]
