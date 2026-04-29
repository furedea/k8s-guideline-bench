"""Tests for dataset instance behavior-preservation verification."""

import subprocess
from pathlib import Path

import verification
from pytest_mock import MockerFixture


def test_verify_instance_at_none_level_returns_passed_without_calling_git(
    mocker: MockerFixture,
) -> None:
    run = mocker.patch("subprocess.run", autospec=True)

    result = verification.verify_instance(
        sha="abc",
        changed_files=("api/foo.go",),
        repo_path=Path("/tmp/k8s"),
        level=verification.VerificationLevel.NONE,
    )

    assert result.passed is True
    assert result.level == verification.VerificationLevel.NONE
    run.assert_not_called()


def test_verify_instance_at_build_level_passes_when_go_build_succeeds(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    prepare = mocker.patch(
        "verification._prepare_worktree",
        autospec=True,
        return_value=tmp_path / "worktree",
    )
    cleanup = mocker.patch("verification._cleanup_worktree", autospec=True)
    build = mocker.patch(
        "subprocess.run",
        autospec=True,
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = verification.verify_instance(
        sha="abc123",
        changed_files=("api/foo.go", "api/foo_test.go"),
        repo_path=Path("/tmp/k8s"),
        level=verification.VerificationLevel.BUILD,
    )

    assert result.passed is True
    assert result.error_excerpt == ""
    prepare.assert_called_once_with(Path("/tmp/k8s"), "abc123")
    cleanup.assert_called_once_with(Path("/tmp/k8s"), tmp_path / "worktree")
    build_call = build.call_args
    assert build_call.args[0][:2] == ["go", "build"]
    assert "./api/..." in build_call.args[0]


def test_verify_instance_at_build_level_fails_and_captures_stderr(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    _ = mocker.patch(
        "verification._prepare_worktree",
        autospec=True,
        return_value=tmp_path / "worktree",
    )
    _ = mocker.patch("verification._cleanup_worktree", autospec=True)
    _ = mocker.patch(
        "subprocess.run",
        autospec=True,
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="api/foo.go: syntax error near unexpected token\n",
        ),
    )

    result = verification.verify_instance(
        sha="abc123",
        changed_files=("api/foo.go",),
        repo_path=Path("/tmp/k8s"),
        level=verification.VerificationLevel.BUILD,
    )

    assert result.passed is False
    assert "syntax error" in result.error_excerpt


def test_verify_instance_skips_go_build_when_no_go_files_changed(
    mocker: MockerFixture,
) -> None:
    run = mocker.patch("subprocess.run", autospec=True)

    result = verification.verify_instance(
        sha="sha",
        changed_files=("docs/README.md",),
        repo_path=Path("/tmp/k8s"),
        level=verification.VerificationLevel.BUILD,
    )

    assert result.passed is True
    run.assert_not_called()


def test_derive_go_packages_returns_sorted_unique_parent_directories() -> None:
    assert verification.derive_go_packages(
        ("api/core/v1/foo.go", "api/core/v1/bar.go", "pkg/util/x.go", "README.md"),
    ) == ("./api/core/v1/...", "./pkg/util/...")
