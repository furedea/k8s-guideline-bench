from pathlib import Path

import error
import normative_constraint
import pytest


def test_load_normative_constraints_reads_json_definition(tmp_path: Path) -> None:
    constraints_file = tmp_path / "normative_constraints.json"
    _ = constraints_file.write_text(
        """
{
  "constraints": [
    {
      "id": "norm_001",
      "source_path": "docs/source/api-conventions.md",
      "source_span": "1-2",
      "text": "All JSON objects returned by an API MUST have kind and apiVersion.",
      "strength_signal": "MUST",
      "atomicizable": true,
      "notes": ""
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    constraints = normative_constraint.load_normative_constraints(constraints_file)

    assert constraints[0].id == "norm_001"
    assert constraints[0].strength_signal == normative_constraint.NormativeSignal.MUST_UPPER


def test_load_normative_constraints_rejects_invalid_shape(tmp_path: Path) -> None:
    constraints_file = tmp_path / "normative_constraints.json"
    _ = constraints_file.write_text("{}", encoding="utf-8")

    with pytest.raises(error.ConstraintCatalogError):
        _ = normative_constraint.load_normative_constraints(constraints_file)


def test_load_normative_constraints_accepts_preferred_strength(tmp_path: Path) -> None:
    constraints_file = tmp_path / "normative_constraints.json"
    _ = constraints_file.write_text(
        """
{
  "constraints": [
    {
      "id": "norm_002",
      "source_path": "docs/source/api-conventions.md",
      "source_span": "1-2",
      "text": "fooPeriodSeconds is preferred for periodic intervals.",
      "strength_signal": "preferred",
      "atomicizable": true,
      "notes": ""
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    constraints = normative_constraint.load_normative_constraints(constraints_file)

    assert constraints[0].strength_signal == normative_constraint.NormativeSignal.PREFERRED
