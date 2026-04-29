"""Behavior-preservation verification for dataset instances via `go build`."""

import enum
import subprocess
import uuid
from pathlib import Path

import base
import pydantic

_STDERR_EXCERPT_CHARS = 1024


class VerificationLevel(enum.StrEnum):
    """Scope of the behavior-preservation check."""

    NONE = "none"
    BUILD = "build"


class VerificationResult(base.FrozenModel):
    """Outcome of verifying a dataset instance."""

    sha: str
    level: VerificationLevel
    passed: bool
    error_excerpt: str = ""

    @pydantic.field_validator("level", mode="before")
    @classmethod
    def validate_level(cls, value: object) -> object:
        if isinstance(value, str):
            return VerificationLevel(value)
        return value


def verify_instance(
    sha: str,
    changed_files: tuple[str, ...],
    repo_path: Path,
    level: VerificationLevel,
) -> VerificationResult:
    """Verify the instance at the requested level; returns passed=True for NONE."""
    if level == VerificationLevel.NONE:
        return VerificationResult(sha=sha, level=level, passed=True)
    return _verify_build(sha, changed_files, repo_path)


def derive_go_packages(changed_files: tuple[str, ...]) -> tuple[str, ...]:
    """Return unique `./<dir>/...` package specs for directories holding Go files."""
    directories = {str(Path(path).parent) for path in changed_files if path.endswith(".go")}
    return tuple(f"./{directory}/..." for directory in sorted(directories))


def _verify_build(
    sha: str,
    changed_files: tuple[str, ...],
    repo_path: Path,
) -> VerificationResult:
    packages = derive_go_packages(changed_files)
    if not packages:
        return VerificationResult(sha=sha, level=VerificationLevel.BUILD, passed=True)
    worktree_dir = _prepare_worktree(repo_path, sha)
    try:
        completed = subprocess.run(
            ["go", "build", *packages],
            cwd=worktree_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        _cleanup_worktree(repo_path, worktree_dir)
    return VerificationResult(
        sha=sha,
        level=VerificationLevel.BUILD,
        passed=completed.returncode == 0,
        error_excerpt=_clip_stderr(completed.stderr) if completed.returncode != 0 else "",
    )


def _prepare_worktree(repo_path: Path, sha: str) -> Path:
    worktree_dir = repo_path.parent / f".verification_worktree_{sha[:12]}_{uuid.uuid4().hex[:8]}"
    _ = subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "--detach", str(worktree_dir), sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return worktree_dir


def _cleanup_worktree(repo_path: Path, worktree_dir: Path) -> None:
    _ = subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree_dir)],
        check=False,
        capture_output=True,
        text=True,
    )


def _clip_stderr(stderr: str) -> str:
    if len(stderr) <= _STDERR_EXCERPT_CHARS:
        return stderr
    return stderr[-_STDERR_EXCERPT_CHARS:]
