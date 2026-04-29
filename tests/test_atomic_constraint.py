from pathlib import Path

import atomic_constraint
import error
import pytest


def test_load_atomic_constraints_reads_json_definition(tmp_path: Path) -> None:
    constraints_file = tmp_path / "atomic_constraints.json"
    _ = constraints_file.write_text(
        """
{
  "constraints": [
    {
      "id": "atom_001",
      "normative_source_ids": ["norm_001"],
      "source_path": "community/contributors/devel/sig-architecture/api-conventions.md",
      "source_span": "1-2",
      "title": "Kind and apiVersion",
      "rule": "All JSON objects returned by an API include kind and apiVersion.",
      "rationale": "Direct decomposition of normative statement.",
      "judgeability": "machine_checkable"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    constraints = atomic_constraint.load_atomic_constraints(constraints_file)

    assert constraints[0].id == "atom_001"
    assert constraints[0].judgeability == atomic_constraint.Judgeability.MACHINE_CHECKABLE


def test_load_atomic_constraints_rejects_invalid_shape(tmp_path: Path) -> None:
    constraints_file = tmp_path / "atomic_constraints.json"
    _ = constraints_file.write_text("{}", encoding="utf-8")

    with pytest.raises(error.ConstraintCatalogError):
        _ = atomic_constraint.load_atomic_constraints(constraints_file)


def test_render_atomic_summary_includes_rule_row() -> None:
    constraints = (
        atomic_constraint.AtomicConstraint(
            id="atom_001",
            normative_source_ids=("norm_001",),
            source_path=Path("community/contributors/devel/sig-architecture/api-conventions.md"),
            source_span="1-2",
            title="Kind and apiVersion",
            rule="All JSON objects returned by an API include kind and apiVersion.",
            rationale="Direct decomposition of normative statement.",
            judgeability=atomic_constraint.Judgeability.MACHINE_CHECKABLE,
        ),
    )

    summary = atomic_constraint.render_atomic_summary(constraints)

    assert "atom_001" in summary
    assert "machine_checkable" in summary
