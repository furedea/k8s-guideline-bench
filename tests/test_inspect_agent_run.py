"""Executable specification for the agent run inspection script."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "inspect_agent_run.py"


def test_inspect_paths_summarizes_metadata_settings_and_trajectory(tmp_path: Path) -> None:
    inspector = _load_inspector()
    run_dir = tmp_path / "results" / "local_100" / "local100_mini_qwen36_fp8_no_constraints" / "100108"
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "run_metadata.json",
        {
            "status": "failed",
            "failure_reason": "agent_budget_exceeded",
            "duration_seconds": 123.45,
            "exit_code": 1,
            "predicted_patch_bytes": 12,
            "pr_number": 100108,
        },
    )
    _ = (run_dir / "mini_swe_agent_settings.env").write_text("step_limit=20\n", encoding="utf-8")
    _write_json(
        run_dir / "trajectory.json",
        {
            "info": {
                "exit_status": "LimitsExceeded",
                "model_stats": {"api_calls": 20},
            },
            "messages": [
                {"role": "user", "content": "abcd"},
                {"role": "assistant", "content": "efghijkl"},
            ],
        },
    )
    _ = (run_dir / "mini_swe_agent_stderr.log").write_text("stderr", encoding="utf-8")

    inspections = inspector.inspect_paths((run_dir,))

    assert len(inspections) == 1
    inspection = inspections[0]
    assert inspection.run_id == "local100_mini_qwen36_fp8_no_constraints"
    assert inspection.pr_number == "100108"
    assert inspection.status == "failed"
    assert inspection.failure_reason == "agent_budget_exceeded"
    assert inspection.duration_seconds == 123.45
    assert inspection.exit_code == 1
    assert inspection.predicted_patch_bytes == 12
    assert inspection.step_limit == "20"
    assert inspection.api_calls == 20
    assert inspection.exit_status == "LimitsExceeded"
    assert inspection.message_count == 2
    assert inspection.estimated_context_tokens == 3
    assert inspection.largest_message_tokens == 2
    assert inspection.largest_message_role == "assistant"
    assert inspection.stderr_bytes == 6


def test_inspect_paths_accepts_results_root_and_formats_a_stable_table(tmp_path: Path) -> None:
    inspector = _load_inspector()
    first_run_dir = tmp_path / "results" / "local_100" / "run-a" / "100108"
    second_run_dir = tmp_path / "results" / "local_100" / "run-b" / "100216"
    first_run_dir.mkdir(parents=True)
    second_run_dir.mkdir(parents=True)
    _write_json(first_run_dir / "run_metadata.json", {"status": "completed", "pr_number": 100108})
    _write_json(
        second_run_dir / "run_metadata.json", {"status": "failed", "failure_reason": "timeout", "pr_number": 100216}
    )

    inspections = inspector.inspect_paths((tmp_path / "results" / "local_100",))
    output = inspector.format_inspections(inspections)

    assert [inspection.path for inspection in inspections] == [first_run_dir, second_run_dir]
    assert "run_id  pr      status     reason" in output
    assert "ctx_est  max_msg  max_role" in output
    assert "run-a   100108  completed  -" in output
    assert "run-b   100216  failed     timeout" in output


def test_main_can_limit_output_to_latest_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inspector = _load_inspector()
    old_run_dir = tmp_path / "results" / "local_100" / "run-old" / "100108"
    new_run_dir = tmp_path / "results" / "local_100" / "run-new" / "100216"
    old_run_dir.mkdir(parents=True)
    new_run_dir.mkdir(parents=True)
    old_metadata = old_run_dir / "run_metadata.json"
    new_metadata = new_run_dir / "run_metadata.json"
    _write_json(old_metadata, {"status": "completed", "pr_number": 100108})
    _write_json(new_metadata, {"status": "failed", "failure_reason": "timeout", "pr_number": 100216})
    os.utime(old_metadata, (1, 1))
    os.utime(new_metadata, (2, 2))

    exit_code = inspector.main((str(tmp_path / "results" / "local_100"), "--latest", "1"))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "run-new" in output
    assert "run-old" not in output


def _load_inspector() -> ModuleType:
    spec = importlib.util.spec_from_file_location("inspect_agent_run", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, document: object) -> None:
    _ = path.write_text(json.dumps(document), encoding="utf-8")
