"""Build per-PR dataset instances for AI agent evaluation."""

import json
import logging
import shutil
import subprocess
from pathlib import Path

import base
import dataset_spec
import pr_collection
import tqdm
import verification

logger = logging.getLogger(__name__)

TASK_FILENAME = "task.json"
GOLD_PATCH_FILENAME = "gold_patch.diff"
BASE_SUBDIR = "base"
GOLD_SUBDIR = "gold"


class GitObjectMissingError(ValueError):
    """Raised when git cannot resolve a path at a specific commit."""

    def __init__(self, path: str, sha: str) -> None:
        super().__init__(f"File {path!r} does not exist at commit {sha!r}")
        self.path = path
        self.sha = sha


class EmptyGoldPatchError(ValueError):
    """Raised when a PR has no materialized diff for the selected changed files."""

    def __init__(self, pr_number: int) -> None:
        super().__init__(f"PR {pr_number} has an empty gold patch")
        self.pr_number = pr_number


class DatasetInstance(base.FrozenModel):
    """On-disk dataset instance produced for a single merged PR."""

    detail: pr_collection.PullRequestDetail
    root: Path


def build_dataset_instances(
    details: tuple[pr_collection.PullRequestDetail, ...],
    repo_path: Path,
    datasets_root: Path,
) -> tuple[DatasetInstance, ...]:
    """Materialize dataset instances for a batch of merged PRs."""
    progress = tqdm.tqdm(details, desc="Materializing", unit="pr")
    instances: list[DatasetInstance] = []
    failed_numbers: list[int] = []
    for detail in progress:
        try:
            instances.append(build_dataset_instance(detail, repo_path, datasets_root))
        except EmptyGoldPatchError:
            failed_numbers.append(detail.pr_number)
            logger.warning(
                {
                    "action": "skip_empty_gold_patch",
                    "pr_number": detail.pr_number,
                }
            )
    if failed_numbers:
        logger.warning(
            {
                "action": "materialize_skipped",
                "empty_gold_patch_count": len(failed_numbers),
                "empty_gold_patch_pr_numbers": failed_numbers,
            }
        )
    return tuple(instances)


def build_dataset_from_spec(spec: dataset_spec.DatasetSpec) -> tuple[DatasetInstance, ...]:
    """Run the full collect → filter → materialize pipeline for a DatasetSpec."""
    effective_since = resolve_effective_since(spec.since, spec.model_cutoffs)
    logger.info(
        {
            "action": "search_prs",
            "since": effective_since,
            "labels": spec.pr_search_labels,
            "repo": spec.github_repo,
        }
    )
    details = pr_collection.collect_pull_requests(
        github_repo=spec.github_repo,
        since=effective_since,
        search_labels=spec.pr_search_labels,
        cache_dir=spec.pr_cache_dir,
        limit=spec.pr_search_limit,
        until=spec.pr_search_until,
        window_days=spec.pr_search_window_days,
    )
    logger.info({"action": "fetch_details_done", "count": len(details)})
    label_filtered = tuple(
        detail
        for detail in details
        if pr_collection.passes_label_filters(
            detail.labels,
            required=spec.required_pr_labels,
            excluded=spec.excluded_pr_labels,
        )
    )
    logger.info(
        {
            "action": "filter_labels",
            "kept": len(label_filtered),
            "dropped": len(details) - len(label_filtered),
        }
    )
    prefix_filtered = tuple(
        pr_collection.filter_changed_files_by_prefix(detail, spec.target_paths) for detail in label_filtered
    )
    denoised = tuple(
        pr_collection.filter_by_exclusion_patterns(detail, spec.exclusion_patterns) for detail in prefix_filtered
    )
    non_empty = tuple(detail for detail in denoised if detail.changed_files)
    logger.info(
        {
            "action": "filter_path_glob",
            "kept": len(non_empty),
            "dropped": len(label_filtered) - len(non_empty),
        }
    )
    production_go_ok = tuple(detail for detail in non_empty if _passes_production_go_filter(detail, spec))
    logger.info(
        {
            "action": "filter_production_go",
            "kept": len(production_go_ok),
            "dropped": len(non_empty) - len(production_go_ok),
            "enabled": spec.require_production_go_change,
        }
    )
    size_ok = tuple(detail for detail in production_go_ok if _passes_size_filters(detail, spec))
    logger.info(
        {
            "action": "filter_size",
            "kept": len(size_ok),
            "dropped": len(non_empty) - len(size_ok),
        }
    )
    trimmed = _apply_pr_limit(size_ok, spec.pr_limit)
    logger.info({"action": "apply_pr_limit", "pr_limit": spec.pr_limit, "kept": len(trimmed)})
    instances = build_dataset_instances(trimmed, spec.repo_path, spec.datasets_root)
    verified = _verify_and_partition(instances, spec)
    logger.info(
        {
            "action": "verify_done",
            "kept": len(verified),
            "dropped": len(instances) - len(verified),
            "level": spec.verification_level.value,
        }
    )
    return verified


def resolve_effective_since(fallback: str | None, model_cutoffs: dict[str, str]) -> str | None:
    """Return the configured lower bound; model cutoffs are intentionally ignored."""
    _ = model_cutoffs
    return fallback


def build_dataset_instance(
    detail: pr_collection.PullRequestDetail,
    repo_path: Path,
    datasets_root: Path,
) -> DatasetInstance:
    """Materialize base/gold snapshots, gold patch, and task metadata on disk."""
    instance_root = datasets_root / str(detail.pr_number)
    base_dir = instance_root / BASE_SUBDIR
    gold_dir = instance_root / GOLD_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)

    _write_snapshots(repo_path, detail.base_sha, detail.changed_files, base_dir)
    _write_snapshots(repo_path, detail.head_sha, detail.changed_files, gold_dir)
    try:
        _write_gold_patch(instance_root, repo_path, detail)
    except EmptyGoldPatchError:
        shutil.rmtree(instance_root, ignore_errors=True)
        raise
    _write_task_metadata(instance_root, detail)

    return DatasetInstance(detail=detail, root=instance_root)


def _verify_and_partition(
    instances: tuple[DatasetInstance, ...],
    spec: dataset_spec.DatasetSpec,
) -> tuple[DatasetInstance, ...]:
    if spec.verification_level == verification.VerificationLevel.NONE:
        return instances
    passed: list[DatasetInstance] = []
    for instance in tqdm.tqdm(instances, desc="Verifying (go build)", unit="pr"):
        result = verification.verify_instance(
            sha=instance.detail.head_sha,
            changed_files=instance.detail.changed_files,
            repo_path=spec.repo_path,
            level=spec.verification_level,
        )
        if result.passed:
            passed.append(instance)
            continue
        _move_to_rejected(instance, result, spec.rejected_root)
    return tuple(passed)


def _move_to_rejected(
    instance: DatasetInstance,
    result: verification.VerificationResult,
    rejected_root: Path | None,
) -> None:
    if rejected_root is None:
        shutil.rmtree(instance.root, ignore_errors=True)
        return
    rejected_root.mkdir(parents=True, exist_ok=True)
    destination = rejected_root / str(instance.detail.pr_number)
    shutil.rmtree(destination, ignore_errors=True)
    _ = shutil.move(str(instance.root), str(destination))
    _ = (destination / "verification_result.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _passes_size_filters(
    detail: pr_collection.PullRequestDetail,
    spec: dataset_spec.DatasetSpec,
) -> bool:
    return pr_collection.passes_size_thresholds(
        detail,
        min_changed_files=spec.min_changed_files,
        max_changed_files=spec.max_changed_files,
        min_changed_lines=spec.min_changed_lines,
        max_changed_lines=spec.max_changed_lines,
    )


def _passes_production_go_filter(
    detail: pr_collection.PullRequestDetail,
    spec: dataset_spec.DatasetSpec,
) -> bool:
    if not spec.require_production_go_change:
        return True
    return any(_is_production_go_file(path) for path in detail.changed_files)


def _is_production_go_file(path: str) -> bool:
    return path.endswith(".go") and not path.endswith("_test.go")


def _apply_pr_limit(
    details: tuple[pr_collection.PullRequestDetail, ...],
    limit: int | None,
) -> tuple[pr_collection.PullRequestDetail, ...]:
    if limit is None or limit >= len(details):
        return details
    return details[:limit]


def _write_snapshots(
    repo_path: Path,
    sha: str,
    changed_files: tuple[str, ...],
    destination_root: Path,
) -> None:
    for relative_path in changed_files:
        try:
            content = _git_show_file(repo_path, sha, relative_path)
        except GitObjectMissingError:
            continue
        output_path = destination_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _ = output_path.write_bytes(content)


def _write_gold_patch(
    instance_root: Path,
    repo_path: Path,
    detail: pr_collection.PullRequestDetail,
) -> None:
    patch = _git_diff(repo_path, detail.base_sha, detail.head_sha, detail.changed_files)
    if not patch.strip():
        raise EmptyGoldPatchError(detail.pr_number)
    _ = (instance_root / GOLD_PATCH_FILENAME).write_bytes(patch)


def _write_task_metadata(
    instance_root: Path,
    detail: pr_collection.PullRequestDetail,
) -> None:
    _ = (instance_root / TASK_FILENAME).write_text(
        json.dumps(detail.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _git_show_file(repo_path: Path, sha: str, relative_path: str) -> bytes:
    # stderr is captured to keep partial-clone lazy-fetch progress off tqdm's line.
    command = ["git", "show", f"{sha}:{relative_path}"]
    result = subprocess.run(command, cwd=repo_path, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitObjectMissingError(path=relative_path, sha=sha)
    return result.stdout


def _git_diff(
    repo_path: Path,
    base_sha: str,
    head_sha: str,
    changed_files: tuple[str, ...],
) -> bytes:
    command = [
        "git",
        "diff",
        "--no-color",
        base_sha,
        head_sha,
        "--",
        *changed_files,
    ]
    return subprocess.run(command, cwd=repo_path, capture_output=True, check=True).stdout
