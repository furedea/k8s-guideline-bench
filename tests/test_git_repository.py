"""Tests for local git repository preparation."""

from pathlib import Path
from subprocess import CompletedProcess

import git_repository
import pytest
from pytest_mock import MockerFixture


def test_ensure_repository_does_nothing_when_path_is_git_repo(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    repo_path = tmp_path / "kubernetes"
    repo_path.mkdir()
    run = mocker.patch(
        "git_repository.subprocess.run",
        autospec=True,
        return_value=CompletedProcess(
            args=[],
            returncode=0,
            stdout="true\n",
            stderr="",
        ),
    )

    git_repository.ensure_repository(repo_path, "kubernetes/kubernetes")

    assert run.call_count == 1
    assert run.call_args.args[0] == ["git", "-C", str(repo_path), "rev-parse", "--is-inside-work-tree"]


def test_ensure_repository_clones_missing_repo_path(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    repo_path = tmp_path / "kubernetes"
    run = mocker.patch(
        "git_repository.subprocess.run",
        autospec=True,
        return_value=CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr="",
        ),
    )

    git_repository.ensure_repository(repo_path, "kubernetes/kubernetes")

    assert run.call_args.args[0] == [
        "git",
        "clone",
        "--filter=blob:none",
        "https://github.com/kubernetes/kubernetes.git",
        str(repo_path),
    ]


def test_ensure_repository_rejects_existing_non_git_path(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    repo_path = tmp_path / "kubernetes"
    repo_path.mkdir()
    _ = mocker.patch(
        "git_repository.subprocess.run",
        autospec=True,
        return_value=CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        ),
    )

    with pytest.raises(ValueError, match="not a git repository"):
        git_repository.ensure_repository(repo_path, "kubernetes/kubernetes")
