"""Tests for PR-based dataset collection (gh search + gh api)."""

import json
import logging
import subprocess
from pathlib import Path

import pr_collection
import pytest
from pytest_mock import MockerFixture


def _pr_core_payload(
    number: int = 42,
    title: str = "Cleanup foo",
    body: str = "Body text.",
    merge_commit_sha: str = "abc123",
    merged_at: str = "2026-03-01T12:34:56Z",
    labels: tuple[str, ...] = ("kind/cleanup",),
) -> dict[str, object]:
    return {
        "number": number,
        "title": title,
        "body": body,
        "merge_commit_sha": merge_commit_sha,
        "merged_at": merged_at,
        "labels": [{"name": name} for name in labels],
    }


def _pr_files_payload(files: tuple[tuple[str, int, int], ...]) -> list[dict[str, object]]:
    return [
        {"filename": filename, "additions": additions, "deletions": deletions}
        for filename, additions, deletions in files
    ]


def test_fetch_pull_request_detail_combines_core_files_and_parent(mocker: MockerFixture) -> None:
    core = _pr_core_payload()
    files = _pr_files_payload((("api/foo.go", 10, 5), ("api/bar.go", 3, 2)))
    parent = {"parents": [{"sha": "parent123"}]}
    gh_api = mocker.patch("pr_collection._gh_api_json", autospec=True)
    gh_api.side_effect = [core, parent, files]

    detail = pr_collection.fetch_pull_request_detail("kubernetes/kubernetes", pr_number=42)

    assert detail == pr_collection.PullRequestDetail(
        pr_number=42,
        base_sha="parent123",
        head_sha="abc123",
        title="Cleanup foo",
        body="Body text.",
        labels=("kind/cleanup",),
        merged_at="2026-03-01T12:34:56Z",
        changed_files=("api/foo.go", "api/bar.go"),
        added_lines=13,
        deleted_lines=7,
    )
    gh_api.assert_any_call("repos/kubernetes/kubernetes/pulls/42")
    gh_api.assert_any_call("repos/kubernetes/kubernetes/pulls/42/files", paginate=True)
    gh_api.assert_any_call("repos/kubernetes/kubernetes/commits/abc123")


def test_fetch_pull_request_detail_uses_cache_when_available(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    cache_dir = tmp_path / "pr_cache"
    cache_dir.mkdir()
    cached = {
        "pr_number": 7,
        "base_sha": "p",
        "head_sha": "h",
        "title": "t",
        "body": "",
        "labels": ["kind/cleanup"],
        "merged_at": "2026-03-01",
        "changed_files": ["api/foo.go"],
        "added_lines": 1,
        "deleted_lines": 0,
    }
    _ = (cache_dir / "7.json").write_text(json.dumps(cached), encoding="utf-8")
    gh_api = mocker.patch("pr_collection._gh_api_json", autospec=True)

    detail = pr_collection.fetch_pull_request_detail(
        "kubernetes/kubernetes",
        pr_number=7,
        cache_dir=cache_dir,
    )

    gh_api.assert_not_called()
    assert detail.pr_number == 7
    assert detail.head_sha == "h"


def test_fetch_pull_request_detail_writes_cache_after_fetch(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    cache_dir = tmp_path / "pr_cache"
    gh_api = mocker.patch("pr_collection._gh_api_json", autospec=True)
    gh_api.side_effect = [
        _pr_core_payload(number=9, merge_commit_sha="m"),
        {"parents": [{"sha": "pp"}]},
        _pr_files_payload((("api/foo.go", 2, 1),)),
    ]

    _ = pr_collection.fetch_pull_request_detail(
        "kubernetes/kubernetes",
        pr_number=9,
        cache_dir=cache_dir,
    )

    cached = json.loads((cache_dir / "9.json").read_text(encoding="utf-8"))
    assert cached["pr_number"] == 9
    assert cached["base_sha"] == "pp"
    assert cached["head_sha"] == "m"


def test_fetch_pull_request_detail_skips_cached_failures_without_calling_gh(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    cache_dir = tmp_path / "pr_cache"
    failure_dir = cache_dir / "failures"
    failure_dir.mkdir(parents=True)
    _ = (failure_dir / "7.json").write_text(
        json.dumps(
            {
                "pr_number": 7,
                "reason": "merge_commit_unavailable",
                "message": "No commit found for SHA: missing",
            }
        ),
        encoding="utf-8",
    )
    gh_api = mocker.patch("pr_collection._gh_api_json", autospec=True)

    with pytest.raises(pr_collection.PullRequestDetailUnavailableError):
        pr_collection.fetch_pull_request_detail(
            "kubernetes/kubernetes",
            pr_number=7,
            cache_dir=cache_dir,
        )

    gh_api.assert_not_called()


def test_fetch_pull_request_detail_writes_failure_cache_for_missing_merge_commit(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    cache_dir = tmp_path / "pr_cache"
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh", "api"],
        stderr="gh: No commit found for SHA: missing (HTTP 422)\n",
    )
    gh_api = mocker.patch("pr_collection._gh_api_json", autospec=True)
    gh_api.side_effect = [_pr_core_payload(number=7, merge_commit_sha="missing"), error]

    with pytest.raises(subprocess.CalledProcessError):
        pr_collection.fetch_pull_request_detail(
            "kubernetes/kubernetes",
            pr_number=7,
            cache_dir=cache_dir,
        )

    cached = json.loads((cache_dir / "failures" / "7.json").read_text(encoding="utf-8"))
    assert cached["pr_number"] == 7
    assert cached["reason"] == "merge_commit_unavailable"
    assert "HTTP 422" in cached["message"]


def test_gh_api_json_flattens_paginated_array_responses(mocker: MockerFixture) -> None:
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        return_value='[[{"filename": "a.go"}], [{"filename": "b.go"}]]',
    )

    payload = pr_collection._gh_api_json("repos/kubernetes/kubernetes/pulls/1/files", paginate=True)

    assert payload == [{"filename": "a.go"}, {"filename": "b.go"}]
    assert gh.call_args.args[0] == [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        "repos/kubernetes/kubernetes/pulls/1/files",
    ]


def test_gh_api_json_throttles_api_calls(mocker: MockerFixture) -> None:
    pr_collection._last_gh_api_at = None
    monotonic = mocker.patch("pr_collection.time.monotonic", autospec=True)
    monotonic.side_effect = [10.0, 10.3]
    sleep = mocker.patch("pr_collection.time.sleep", autospec=True)
    gh = mocker.patch("pr_collection._gh", autospec=True, return_value="{}")

    _ = pr_collection._gh_api_json("repos/kubernetes/kubernetes/pulls/1")
    _ = pr_collection._gh_api_json("repos/kubernetes/kubernetes/pulls/2")

    assert gh.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_fetch_pull_request_detail_does_not_fetch_files_when_merge_commit_is_missing(
    mocker: MockerFixture,
) -> None:
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh", "api"],
        stderr="gh: No commit found for SHA: missing (HTTP 422)\n",
    )
    gh_api = mocker.patch("pr_collection._gh_api_json", autospec=True)
    gh_api.side_effect = [_pr_core_payload(merge_commit_sha="missing"), error]

    with pytest.raises(subprocess.CalledProcessError):
        pr_collection.fetch_pull_request_detail("kubernetes/kubernetes", pr_number=1)

    assert gh_api.call_args_list[0].args == ("repos/kubernetes/kubernetes/pulls/1",)
    assert gh_api.call_args_list[1].args == ("repos/kubernetes/kubernetes/commits/missing",)


def test_search_merged_pr_numbers_calls_gh_search_with_expected_args(mocker: MockerFixture) -> None:
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        return_value='[{"number": 10}, {"number": 20}]',
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since="2024-01-01",
        search_labels=("kind/cleanup",),
        limit=500,
    )

    assert numbers == (10, 20)
    args = gh.call_args.args[0]
    assert args[0:3] == ["gh", "search", "prs"]
    assert "--repo" in args
    assert "kubernetes/kubernetes" in args
    assert "--merged" in args
    assert "--label" in args
    assert "kind/cleanup" in args
    assert "--merged-at" in args
    assert ">=2024-01-01" in args
    assert "--json" in args
    assert "number" in args
    assert "--limit" in args
    assert "500" in args


def test_search_merged_pr_numbers_splits_large_limit_into_date_windows(mocker: MockerFixture) -> None:
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        side_effect=[
            '[{"number": 10}, {"number": 20}]',
            '[{"number": 20}, {"number": 30}]',
        ],
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since="2024-01-01",
        search_labels=("kind/cleanup",),
        limit=1001,
        until="2024-01-20",
        window_days=10,
    )

    assert numbers == (10, 20, 30)
    assert gh.call_count == 2
    first_args = gh.call_args_list[0].args[0]
    second_args = gh.call_args_list[1].args[0]
    assert first_args[first_args.index("--limit") + 1] == "100"
    assert second_args[second_args.index("--limit") + 1] == "100"
    assert "2024-01-01..2024-01-10" in first_args
    assert "2024-01-11..2024-01-20" in second_args


def test_search_merged_pr_numbers_splits_full_windows_to_avoid_search_pagination(
    mocker: MockerFixture,
) -> None:
    full_page = [{"number": number} for number in range(1, 101)]
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        side_effect=[
            json.dumps(full_page),
            '[{"number": 10}]',
            '[{"number": 20}]',
        ],
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since="2024-01-01",
        search_labels=("kind/cleanup",),
        limit=1001,
        until="2024-01-02",
        window_days=2,
    )

    assert numbers == (10, 20)
    assert gh.call_count == 3
    first_args = gh.call_args_list[0].args[0]
    second_args = gh.call_args_list[1].args[0]
    third_args = gh.call_args_list[2].args[0]
    assert first_args[first_args.index("--limit") + 1] == "100"
    assert "2024-01-01..2024-01-02" in first_args
    assert "2024-01-01..2024-01-01" in second_args
    assert "2024-01-02..2024-01-02" in third_args


def test_search_merged_pr_numbers_splits_full_single_day_by_created_date(
    mocker: MockerFixture,
) -> None:
    full_page = [{"number": number} for number in range(1, 101)]
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        side_effect=[
            json.dumps(full_page),
            '{"createdAt": "2024-01-01T00:00:00Z"}',
            json.dumps(full_page),
            '[{"number": 10}]',
            '[{"number": 20}]',
        ],
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since="2024-01-10",
        search_labels=("kind/cleanup",),
        limit=1001,
        until="2024-01-10",
        window_days=1,
    )

    assert numbers == (10, 20)
    assert gh.call_count == 5
    first_args = gh.call_args_list[0].args[0]
    repository_args = gh.call_args_list[1].args[0]
    created_probe_args = gh.call_args_list[2].args[0]
    second_args = gh.call_args_list[3].args[0]
    third_args = gh.call_args_list[4].args[0]
    assert "2024-01-10..2024-01-10" in first_args
    assert "--created" not in first_args
    assert repository_args == ["gh", "repo", "view", "kubernetes/kubernetes", "--json", "createdAt"]
    assert "2024-01-10..2024-01-10" in created_probe_args
    assert "2024-01-01..2024-01-10" in created_probe_args
    assert "2024-01-10..2024-01-10" in second_args
    assert "2024-01-01..2024-01-05" in second_args
    assert "2024-01-10..2024-01-10" in third_args
    assert "2024-01-06..2024-01-10" in third_args


def test_search_merged_pr_numbers_uses_repository_creation_date_when_since_is_unset(
    mocker: MockerFixture,
) -> None:
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        side_effect=[
            '{"createdAt": "2014-06-06T22:56:04Z"}',
            '[{"number": 10}]',
            '[{"number": 20}]',
        ],
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since=None,
        search_labels=("kind/cleanup",),
        limit=1001,
        until="2014-06-20",
        window_days=10,
    )

    assert numbers == (10, 20)
    repository_args = gh.call_args_list[0].args[0]
    first_search_args = gh.call_args_list[1].args[0]
    second_search_args = gh.call_args_list[2].args[0]
    assert repository_args == ["gh", "repo", "view", "kubernetes/kubernetes", "--json", "createdAt"]
    assert "2014-06-06..2014-06-15" in first_search_args
    assert "2014-06-16..2014-06-20" in second_search_args


def test_search_merged_pr_numbers_skips_failed_date_windows(mocker: MockerFixture) -> None:
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        side_effect=[
            subprocess.CalledProcessError(
                returncode=1,
                cmd=["gh", "search", "prs"],
                stderr="HTTP 422: Validation Failed",
            ),
            '[{"number": 20}]',
        ],
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since="2014-12-19",
        search_labels=("kind/cleanup",),
        limit=1001,
        until="2015-01-01",
        window_days=7,
    )

    assert numbers == (20,)
    assert gh.call_count == 2


def test_search_merged_pr_numbers_throttles_search_api_calls(mocker: MockerFixture) -> None:
    pr_collection._last_gh_search_at = None
    monotonic = mocker.patch("pr_collection.time.monotonic", autospec=True)
    monotonic.side_effect = [10.0, 10.5]
    sleep = mocker.patch("pr_collection.time.sleep", autospec=True)
    gh = mocker.patch(
        "pr_collection._gh",
        autospec=True,
        side_effect=[
            '[{"number": 10}]',
            '[{"number": 20}]',
        ],
    )

    numbers = pr_collection.search_merged_pr_numbers(
        github_repo="kubernetes/kubernetes",
        since="2015-09-11",
        search_labels=("kind/cleanup",),
        limit=1001,
        until="2015-09-24",
        window_days=7,
    )

    assert numbers == (10, 20)
    assert gh.call_count == 2
    sleep.assert_called_once_with(1.6)


def test_gh_does_not_retry_non_retryable_validation_errors(mocker: MockerFixture) -> None:
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh", "api"],
        stderr="gh: No commit found for SHA: abc (HTTP 422)\n",
    )
    run = mocker.patch("pr_collection.subprocess.run", autospec=True, side_effect=error)
    sleep = mocker.patch("pr_collection.time.sleep", autospec=True)

    try:
        pr_collection._gh(["gh", "api", "repos/kubernetes/kubernetes/commits/abc"])
    except subprocess.CalledProcessError as raised:
        assert raised is error

    assert run.call_count == 1
    sleep.assert_not_called()


def test_collect_pull_requests_fetches_detail_for_each_search_hit(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    _ = mocker.patch(
        "pr_collection.search_merged_pr_numbers",
        autospec=True,
        return_value=(1, 2),
    )

    def fake_fetch(
        github_repo: str,
        pr_number: int,
        cache_dir: Path | None = None,
    ) -> pr_collection.PullRequestDetail:
        _ = github_repo, cache_dir
        return pr_collection.PullRequestDetail(
            pr_number=pr_number,
            base_sha=f"base{pr_number}",
            head_sha=f"head{pr_number}",
            title="t",
            body="",
            labels=("kind/cleanup",),
            merged_at="2026-03-01",
            changed_files=("api/foo.go",),
            added_lines=1,
            deleted_lines=0,
        )

    _ = mocker.patch(
        "pr_collection.fetch_pull_request_detail",
        autospec=True,
        side_effect=fake_fetch,
    )

    details = pr_collection.collect_pull_requests(
        github_repo="kubernetes/kubernetes",
        since="2024-01-01",
        search_labels=("kind/cleanup",),
        cache_dir=tmp_path / "cache",
    )

    assert tuple(detail.pr_number for detail in details) == (1, 2)


def test_collect_pull_requests_skips_prs_that_fail_detail_fetch(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    _ = mocker.patch(
        "pr_collection.search_merged_pr_numbers",
        autospec=True,
        return_value=(1, 2, 3),
    )

    def fake_fetch(
        github_repo: str,
        pr_number: int,
        cache_dir: Path | None = None,
    ) -> pr_collection.PullRequestDetail:
        _ = github_repo, cache_dir
        if pr_number == 2:
            raise subprocess.CalledProcessError(returncode=1, cmd=["gh", "api"])
        return pr_collection.PullRequestDetail(
            pr_number=pr_number,
            base_sha=f"base{pr_number}",
            head_sha=f"head{pr_number}",
            title="t",
            body="",
            labels=("kind/cleanup",),
            merged_at="2026-03-01",
            changed_files=("api/foo.go",),
            added_lines=1,
            deleted_lines=0,
        )

    _ = mocker.patch(
        "pr_collection.fetch_pull_request_detail",
        autospec=True,
        side_effect=fake_fetch,
    )

    details = pr_collection.collect_pull_requests(
        github_repo="kubernetes/kubernetes",
        since="2024-01-01",
        search_labels=("kind/cleanup",),
        cache_dir=tmp_path / "cache",
    )

    assert tuple(detail.pr_number for detail in details) == (1, 3)


def test_collect_pull_requests_logs_first_resolvable_pr_after_initial_detail_failures(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    _ = mocker.patch(
        "pr_collection.search_merged_pr_numbers",
        autospec=True,
        return_value=(1, 2, 3),
    )

    def fake_fetch(
        github_repo: str,
        pr_number: int,
        cache_dir: Path | None = None,
    ) -> pr_collection.PullRequestDetail:
        _ = github_repo, cache_dir
        if pr_number in (1, 2):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["gh", "api"],
                stderr="gh: No commit found for SHA: missing (HTTP 422)\n",
            )
        return pr_collection.PullRequestDetail(
            pr_number=3,
            base_sha="base3",
            head_sha="head3",
            title="t",
            body="",
            labels=("kind/cleanup",),
            merged_at="2016-12-22T00:00:00Z",
            changed_files=("api/foo.go",),
            added_lines=1,
            deleted_lines=0,
        )

    _ = mocker.patch(
        "pr_collection.fetch_pull_request_detail",
        autospec=True,
        side_effect=fake_fetch,
    )

    with caplog.at_level(logging.INFO, logger="pr_collection"):
        details = pr_collection.collect_pull_requests(
            github_repo="kubernetes/kubernetes",
            since=None,
            search_labels=("kind/cleanup",),
            cache_dir=tmp_path / "cache",
        )

    assert tuple(detail.pr_number for detail in details) == (3,)
    assert {
        "action": "first_resolvable_pr_after_detail_failures",
        "pr_number": 3,
        "merged_at": "2016-12-22T00:00:00Z",
        "initial_failed_count": 2,
        "last_failed_pr_number": 2,
    } in [record.msg for record in caplog.records]


def test_passes_label_filters_enforces_any_required_and_rejects_excluded() -> None:
    labels = ("kind/cleanup", "area/apimachinery")

    assert pr_collection.passes_label_filters(labels, required=(), excluded=())
    assert pr_collection.passes_label_filters(labels, required=("kind/cleanup",), excluded=())
    assert not pr_collection.passes_label_filters(labels, required=("kind/bug",), excluded=())
    assert not pr_collection.passes_label_filters(
        labels,
        required=(),
        excluded=("area/apimachinery",),
    )


def test_filter_changed_files_by_prefix_keeps_only_target_paths() -> None:
    detail = pr_collection.PullRequestDetail(
        pr_number=1,
        base_sha="b",
        head_sha="h",
        title="t",
        body="",
        labels=(),
        merged_at="2026-03-01",
        changed_files=(
            "api/foo.go",
            "pkg/apis/core/bar.go",
            "docs/README.md",
            "pkg/unrelated/y.go",
        ),
        added_lines=0,
        deleted_lines=0,
    )

    filtered = pr_collection.filter_changed_files_by_prefix(
        detail,
        target_paths=("api", "pkg/apis"),
    )

    assert filtered.changed_files == ("api/foo.go", "pkg/apis/core/bar.go")


def test_filter_by_exclusion_patterns_drops_matching_globs() -> None:
    detail = pr_collection.PullRequestDetail(
        pr_number=1,
        base_sha="b",
        head_sha="h",
        title="t",
        body="",
        labels=(),
        merged_at="2026-03-01",
        changed_files=(
            "api/foo.go",
            "api/zz_generated_deepcopy.go",
            "vendor/lib/util.go",
            "pkg/types.pb.go",
        ),
        added_lines=0,
        deleted_lines=0,
    )

    filtered = pr_collection.filter_by_exclusion_patterns(
        detail,
        exclusion_patterns=("**/zz_generated_*.go", "vendor/**", "**/*.pb.go"),
    )

    assert filtered.changed_files == ("api/foo.go",)


def test_passes_size_thresholds_checks_file_and_line_bounds() -> None:
    detail = pr_collection.PullRequestDetail(
        pr_number=1,
        base_sha="b",
        head_sha="h",
        title="t",
        body="",
        labels=(),
        merged_at="2026-03-01",
        changed_files=("a.go", "b.go"),
        added_lines=100,
        deleted_lines=50,
    )

    assert pr_collection.passes_size_thresholds(
        detail,
        min_changed_files=1,
        max_changed_files=5,
        min_changed_lines=10,
        max_changed_lines=500,
    )
    assert not pr_collection.passes_size_thresholds(
        detail,
        min_changed_files=3,
        max_changed_files=None,
        min_changed_lines=0,
        max_changed_lines=None,
    )
    assert not pr_collection.passes_size_thresholds(
        detail,
        min_changed_files=1,
        max_changed_files=None,
        min_changed_lines=0,
        max_changed_lines=100,
    )
