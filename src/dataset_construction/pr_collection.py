"""Collect merged pull requests via `gh search` + `gh api`.

One merged PR is the collection unit (SWE-bench style whole-PR-as-one).
`PullRequestDetail` captures everything the downstream builder needs to
materialize base/gold snapshots, gold patch, and task metadata without
touching the network again.
"""

import fnmatch
import json
import logging
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import base
import pydantic
import tqdm

logger = logging.getLogger(__name__)

_DATE_GTE_PREFIX = ">="
_GH_SEARCH_LIMIT_MAX = 1000
_GH_SEARCH_PAGE_LIMIT = 100
_GH_ATTEMPTS = 3
_GH_RETRY_BASE_SECONDS = 2.0
_GH_SEARCH_MIN_INTERVAL_SECONDS = 2.1
_GH_API_MIN_INTERVAL_SECONDS = 0.8
_last_gh_search_at: float | None = None
_last_gh_api_at: float | None = None
_FAILURE_CACHE_DIRNAME = "failures"
_MERGE_COMMIT_UNAVAILABLE = "merge_commit_unavailable"


class PullRequestDetailUnavailableError(ValueError):
    """Raised when a PR is known to be unavailable for dataset construction."""


class PullRequestDetail(base.FrozenModel):
    """Metadata for a single merged PR used as one dataset instance."""

    pr_number: int
    base_sha: str
    head_sha: str
    title: str
    body: str
    labels: tuple[str, ...]
    merged_at: str
    changed_files: tuple[str, ...]
    added_lines: int
    deleted_lines: int

    @pydantic.field_validator("changed_files", "labels", mode="before")
    @classmethod
    def validate_string_tuples(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(cast("list[str]", value))
        return value


_DETAIL_ADAPTER = pydantic.TypeAdapter(PullRequestDetail)


def collect_pull_requests(
    github_repo: str,
    since: str | None,
    search_labels: tuple[str, ...],
    cache_dir: Path | None = None,
    limit: int = 1000,
    until: str | None = None,
    window_days: int = 30,
) -> tuple[PullRequestDetail, ...]:
    """List merged PRs matching `search_labels` and fetch full detail for each."""
    pr_numbers = search_merged_pr_numbers(
        github_repo=github_repo,
        since=since,
        search_labels=search_labels,
        limit=limit,
        until=until,
        window_days=window_days,
    )
    logger.info({"action": "search_done", "count": len(pr_numbers)})
    progress = tqdm.tqdm(pr_numbers, desc="PR details", unit="pr", ncols=88)
    details: list[PullRequestDetail] = []
    failed_numbers: list[int] = []
    initial_failed_numbers: list[int] = []
    found_first_detail = False
    for pr_number in progress:
        try:
            detail = fetch_pull_request_detail(github_repo, pr_number, cache_dir=cache_dir)
            details.append(detail)
            if not found_first_detail and initial_failed_numbers:
                logger.info(
                    {
                        "action": "first_resolvable_pr_after_detail_failures",
                        "pr_number": detail.pr_number,
                        "merged_at": detail.merged_at,
                        "initial_failed_count": len(initial_failed_numbers),
                        "last_failed_pr_number": initial_failed_numbers[-1],
                    }
                )
            found_first_detail = True
        except (
            PullRequestDetailUnavailableError,
            json.JSONDecodeError,
            pydantic.ValidationError,
            subprocess.CalledProcessError,
        ) as fetch_error:
            failed_numbers.append(pr_number)
            if not found_first_detail:
                initial_failed_numbers.append(pr_number)
            logger.warning(
                {
                    "action": "skip_pr_detail_fetch_failed",
                    "pr_number": pr_number,
                    "error": str(fetch_error),
                }
            )
    if failed_numbers:
        logger.warning(
            {
                "action": "fetch_details_skipped",
                "failed_count": len(failed_numbers),
                "failed_pr_numbers": failed_numbers,
            }
        )
    return tuple(details)


def search_merged_pr_numbers(
    github_repo: str,
    since: str | None,
    search_labels: tuple[str, ...],
    limit: int,
    until: str | None = None,
    window_days: int = 30,
) -> tuple[int, ...]:
    """Return PR numbers of merged PRs matching all `search_labels`."""
    if limit <= _GH_SEARCH_LIMIT_MAX:
        return _search_merged_pr_numbers_once(
            github_repo=github_repo,
            merged_at=f"{_DATE_GTE_PREFIX}{since}" if since else None,
            search_labels=search_labels,
            limit=limit,
        )

    return _search_merged_pr_numbers_by_date_window(
        github_repo=github_repo,
        since=since,
        until=until,
        search_labels=search_labels,
        limit=limit,
        window_days=window_days,
    )


def _search_merged_pr_numbers_once(
    github_repo: str,
    merged_at: str | None,
    search_labels: tuple[str, ...],
    limit: int,
    created_at: str | None = None,
) -> tuple[int, ...]:
    _throttle_gh_search()
    args = [
        "gh",
        "search",
        "prs",
        "--repo",
        github_repo,
        "--merged",
        "--json",
        "number",
        "--limit",
        str(limit),
    ]
    if merged_at:
        args.extend(["--merged-at", merged_at])
    if created_at:
        args.extend(["--created", created_at])
    for label in search_labels:
        args.extend(["--label", label])
    raw = _gh(args)
    entries: list[dict[str, Any]] = json.loads(raw)
    return tuple(int(entry["number"]) for entry in entries)


def _throttle_gh_search() -> None:
    global _last_gh_search_at  # noqa: PLW0603

    _last_gh_search_at = _throttle_since(_last_gh_search_at, _GH_SEARCH_MIN_INTERVAL_SECONDS)


def _throttle_gh_api() -> None:
    global _last_gh_api_at  # noqa: PLW0603

    _last_gh_api_at = _throttle_since(_last_gh_api_at, _GH_API_MIN_INTERVAL_SECONDS)


def _throttle_since(last_called_at: float | None, min_interval_seconds: float) -> float:
    now = time.monotonic()
    if last_called_at is not None:
        elapsed = now - last_called_at
        if elapsed < min_interval_seconds:
            delay = round(min_interval_seconds - elapsed, 1)
            time.sleep(delay)
            return now + delay
    return now


def _search_merged_pr_numbers_by_date_window(
    github_repo: str,
    since: str | None,
    until: str | None,
    search_labels: tuple[str, ...],
    limit: int,
    window_days: int,
) -> tuple[int, ...]:
    if window_days < 1:
        raise ValueError("window_days must be greater than 0")

    effective_since = since or fetch_repository_created_date(github_repo)
    merged_until = date.fromisoformat(until) if until is not None else datetime.now(UTC).date()
    numbers: list[int] = []
    seen: set[int] = set()
    for start, end in _date_windows(date.fromisoformat(effective_since), merged_until, window_days):
        try:
            window_numbers = _search_merged_pr_numbers_by_bounded_window(
                github_repo=github_repo,
                start=start,
                end=end,
                search_labels=search_labels,
            )
        except subprocess.CalledProcessError as search_error:
            logger.warning(
                {
                    "action": "skip_pr_search_window_failed",
                    "merged_at": _merged_at_range(start, end),
                    "error": str(search_error),
                    "stderr": search_error.stderr,
                }
            )
            continue
        for number in window_numbers:
            if number in seen:
                continue
            seen.add(number)
            numbers.append(number)
            if len(numbers) >= limit:
                return tuple(numbers)
    return tuple(numbers)


def _search_merged_pr_numbers_by_bounded_window(
    github_repo: str,
    start: date,
    end: date,
    search_labels: tuple[str, ...],
) -> tuple[int, ...]:
    window_numbers = _search_merged_pr_numbers_once(
        github_repo=github_repo,
        merged_at=_merged_at_range(start, end),
        search_labels=search_labels,
        limit=_GH_SEARCH_PAGE_LIMIT,
    )
    if len(window_numbers) < _GH_SEARCH_PAGE_LIMIT:
        return window_numbers
    if start == end:
        repository_created = date.fromisoformat(fetch_repository_created_date(github_repo))
        return _search_merged_pr_numbers_by_created_window(
            github_repo=github_repo,
            merged_at=_merged_at_range(start, end),
            created_start=repository_created,
            created_end=end,
            search_labels=search_labels,
        )

    midpoint = start + timedelta(days=(end - start).days // 2)
    logger.info(
        {
            "action": "split_full_pr_search_window",
            "merged_at": _merged_at_range(start, end),
            "count": len(window_numbers),
        }
    )
    left = _search_merged_pr_numbers_by_bounded_window(
        github_repo=github_repo,
        start=start,
        end=midpoint,
        search_labels=search_labels,
    )
    right = _search_merged_pr_numbers_by_bounded_window(
        github_repo=github_repo,
        start=midpoint + timedelta(days=1),
        end=end,
        search_labels=search_labels,
    )
    return (*left, *right)


def _search_merged_pr_numbers_by_created_window(
    github_repo: str,
    merged_at: str,
    created_start: date,
    created_end: date,
    search_labels: tuple[str, ...],
) -> tuple[int, ...]:
    if created_start > created_end:
        return ()
    window_numbers = _search_merged_pr_numbers_once(
        github_repo=github_repo,
        merged_at=merged_at,
        search_labels=search_labels,
        limit=_GH_SEARCH_PAGE_LIMIT,
        created_at=_merged_at_range(created_start, created_end),
    )
    if len(window_numbers) < _GH_SEARCH_PAGE_LIMIT or created_start == created_end:
        if len(window_numbers) == _GH_SEARCH_PAGE_LIMIT:
            logger.warning(
                {
                    "action": "single_day_pr_search_window_still_full",
                    "merged_at": merged_at,
                    "created": _merged_at_range(created_start, created_end),
                    "count": len(window_numbers),
                }
            )
        return window_numbers

    midpoint = created_start + timedelta(days=(created_end - created_start).days // 2)
    logger.info(
        {
            "action": "split_full_pr_search_created_window",
            "merged_at": merged_at,
            "created": _merged_at_range(created_start, created_end),
            "count": len(window_numbers),
        }
    )
    left = _search_merged_pr_numbers_by_created_window(
        github_repo=github_repo,
        merged_at=merged_at,
        created_start=created_start,
        created_end=midpoint,
        search_labels=search_labels,
    )
    right = _search_merged_pr_numbers_by_created_window(
        github_repo=github_repo,
        merged_at=merged_at,
        created_start=midpoint + timedelta(days=1),
        created_end=created_end,
        search_labels=search_labels,
    )
    return (*left, *right)


def _merged_at_range(start: date, end: date) -> str:
    return f"{start.isoformat()}..{end.isoformat()}"


def fetch_repository_created_date(github_repo: str) -> str:
    """Return the GitHub repository creation date as an ISO date."""
    raw = _gh(["gh", "repo", "view", github_repo, "--json", "createdAt"])
    payload: dict[str, str] = json.loads(raw)
    created_at = payload["createdAt"]
    return datetime.fromisoformat(created_at).date().isoformat()


def _date_windows(
    since: date,
    until: date,
    window_days: int,
) -> tuple[tuple[date, date], ...]:
    windows: list[tuple[date, date]] = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=window_days - 1), until)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return tuple(windows)


def fetch_pull_request_detail(
    github_repo: str,
    pr_number: int,
    cache_dir: Path | None = None,
) -> PullRequestDetail:
    """Fetch title/body/labels, changed files, and parent SHA for one merged PR."""
    if cache_dir is not None:
        cached_failure = _read_failure_cache(cache_dir, pr_number)
        if cached_failure is not None:
            raise PullRequestDetailUnavailableError(cached_failure)
        cached = _read_cache(cache_dir, pr_number)
        if cached is not None:
            return cached
    core = _gh_api_json(f"repos/{github_repo}/pulls/{pr_number}")
    head_sha = str(core["merge_commit_sha"])
    try:
        commit_payload = _gh_api_json(f"repos/{github_repo}/commits/{head_sha}")
    except subprocess.CalledProcessError as error:
        if cache_dir is not None and _is_non_retryable_gh_error(error):
            _write_failure_cache(
                cache_dir=cache_dir,
                pr_number=pr_number,
                reason=_MERGE_COMMIT_UNAVAILABLE,
                message=_optional_text(error.stderr) or str(error),
            )
        raise
    base_sha = str(commit_payload["parents"][0]["sha"])
    files = _gh_api_json(f"repos/{github_repo}/pulls/{pr_number}/files", paginate=True)
    detail = PullRequestDetail(
        pr_number=int(core["number"]),
        base_sha=base_sha,
        head_sha=head_sha,
        title=_optional_text(core.get("title")),
        body=_optional_text(core.get("body")),
        labels=tuple(entry["name"] for entry in core.get("labels", [])),
        merged_at=_optional_text(core.get("merged_at")),
        changed_files=tuple(entry["filename"] for entry in files),
        added_lines=sum(int(entry.get("additions", 0)) for entry in files),
        deleted_lines=sum(int(entry.get("deletions", 0)) for entry in files),
    )
    if cache_dir is not None:
        _write_cache(cache_dir, detail)
    return detail


def passes_label_filters(
    labels: tuple[str, ...],
    required: tuple[str, ...],
    excluded: tuple[str, ...],
) -> bool:
    """Return True when `labels` satisfy required (ANY-OF) and excluded sets."""
    if required and not any(label in labels for label in required):
        return False
    if any(label in labels for label in excluded):
        return False
    return True


def filter_changed_files_by_prefix(
    detail: PullRequestDetail,
    target_paths: tuple[str, ...],
) -> PullRequestDetail:
    """Drop changed files outside the configured target path prefixes."""
    kept = tuple(path for path in detail.changed_files if _has_target_prefix(path, target_paths))
    return detail.model_copy(update={"changed_files": kept})


def filter_by_exclusion_patterns(
    detail: PullRequestDetail,
    exclusion_patterns: tuple[str, ...],
) -> PullRequestDetail:
    """Drop changed files whose path matches any exclusion glob pattern."""
    if not exclusion_patterns:
        return detail
    kept = tuple(path for path in detail.changed_files if not _matches_any_pattern(path, exclusion_patterns))
    return detail.model_copy(update={"changed_files": kept})


def passes_size_thresholds(
    detail: PullRequestDetail,
    min_changed_files: int,
    max_changed_files: int | None,
    min_changed_lines: int,
    max_changed_lines: int | None,
) -> bool:
    """Check whether a PR's file count and line delta fall within bounds."""
    file_count = len(detail.changed_files)
    if file_count < min_changed_files:
        return False
    if max_changed_files is not None and file_count > max_changed_files:
        return False
    total_lines = detail.added_lines + detail.deleted_lines
    if total_lines < min_changed_lines:
        return False
    if max_changed_lines is not None and total_lines > max_changed_lines:
        return False
    return True


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _gh(args: list[str]) -> str:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, _GH_ATTEMPTS + 1):
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as error:
            last_error = error
            if _is_non_retryable_gh_error(error):
                break
            if attempt == _GH_ATTEMPTS:
                break
            logger.warning(
                {
                    "action": "gh_retry",
                    "attempt": attempt,
                    "max_attempts": _GH_ATTEMPTS,
                    "cmd": args,
                    "stderr": error.stderr,
                }
            )
            time.sleep(_GH_RETRY_BASE_SECONDS * attempt)
    if last_error is None:
        raise RuntimeError("gh command failed without an exception")
    raise last_error


def _is_non_retryable_gh_error(error: subprocess.CalledProcessError) -> bool:
    return "HTTP 422" in _optional_text(error.stderr)


def _gh_api_json(path: str, paginate: bool = False) -> Any:
    _throttle_gh_api()
    args = ["gh", "api"]
    if paginate:
        args.extend(["--paginate", "--slurp"])
    args.append(path)
    payload: Any = json.loads(_gh(args))
    if paginate and isinstance(payload, list):
        page_candidates = cast("list[Any]", payload)
        if all(isinstance(page, list) for page in page_candidates):
            pages = cast("list[list[Any]]", page_candidates)
            flattened: list[Any] = []
            for page in pages:
                flattened.extend(page)
            return flattened
    return payload


def _read_cache(cache_dir: Path, pr_number: int) -> PullRequestDetail | None:
    cache_path = cache_dir / f"{pr_number}.json"
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return _DETAIL_ADAPTER.validate_python(json.loads(raw))


def _read_failure_cache(cache_dir: Path, pr_number: int) -> str | None:
    cache_path = _failure_cache_path(cache_dir, pr_number)
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    payload: dict[str, object] = json.loads(raw)
    return _optional_text(payload.get("message"))


def _write_cache(cache_dir: Path, detail: PullRequestDetail) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{detail.pr_number}.json"
    _ = cache_path.write_text(
        json.dumps(detail.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_failure_cache(
    cache_dir: Path,
    pr_number: int,
    reason: str,
    message: str,
) -> None:
    cache_path = _failure_cache_path(cache_dir, pr_number)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _ = cache_path.write_text(
        json.dumps(
            {
                "pr_number": pr_number,
                "reason": reason,
                "message": message,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _failure_cache_path(cache_dir: Path, pr_number: int) -> Path:
    return cache_dir / _FAILURE_CACHE_DIRNAME / f"{pr_number}.json"


def _has_target_prefix(path: str, target_paths: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in target_paths)


def _matches_any_pattern(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
