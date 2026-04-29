"""Helpers for ensuring external git repositories are available locally."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_repository(repo_path: Path, github_repo: str) -> None:
    """Clone the GitHub repository when `repo_path` does not exist."""
    if _is_git_repository(repo_path):
        return
    if repo_path.exists():
        msg = f"Repository path exists but is not a git repository: {repo_path}"
        raise ValueError(msg)
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://github.com/{github_repo}.git"
    logger.info(
        {
            "action": "clone_repository",
            "repo": github_repo,
            "repo_path": str(repo_path),
            "url": clone_url,
        },
    )
    _ = subprocess.run(
        ["git", "clone", "--filter=blob:none", clone_url, str(repo_path)],
        check=True,
    )


def _is_git_repository(path: Path) -> bool:
    if not path.exists():
        return False
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"
