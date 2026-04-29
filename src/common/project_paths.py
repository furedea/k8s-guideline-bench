"""Project path definitions."""

from pathlib import Path

import base


def resolve_under(project_root: Path, path: Path) -> Path:
    """Return `path` if absolute, else interpret it relative to `project_root`."""
    return path if path.is_absolute() else project_root / path


class ProjectPaths(base.FrozenModel):
    """Resolved project directory layout."""

    root: Path
    constraints_directory: Path
    constraints_file: Path
    config_directory: Path
    datasets_directory: Path
    results_directory: Path
    src_directory: Path
    tests_directory: Path

    @classmethod
    def from_root(cls, root: Path) -> ProjectPaths:
        """Build project paths from the repository root."""
        constraints_directory = root / "constraints"
        config_directory = root / "config"
        return cls(
            root=root,
            constraints_directory=constraints_directory,
            constraints_file=constraints_directory / "atomic_constraints.json",
            config_directory=config_directory,
            datasets_directory=root / "datasets",
            results_directory=root / "results",
            src_directory=root / "src",
            tests_directory=root / "tests",
        )
