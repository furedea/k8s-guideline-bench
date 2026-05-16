"""Static checks for local agent operation helpers."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_smoke_local_agent_script_runs_only_the_agent_stage() -> None:
    script = (REPO_ROOT / "scripts" / "smoke_local_agent.sh").read_text(encoding="utf-8")

    assert "src/agent_execution/run_agent.py" in script
    assert "src/llm_judgment/run_experiment.py" not in script
    assert "scripts/inspect_agent_run.py" in script
    assert "results_root" in script


def test_smoke_local_agent_script_has_bash_guardrails() -> None:
    script = (REPO_ROOT / "scripts" / "smoke_local_agent.sh").read_text(encoding="utf-8")

    assert script.startswith('#!/bin/bash\nset -euxCo pipefail\ncd "$(dirname "$0")"\n')
    assert "function usage()" in script
    assert "LOCAL_LLM_API_KEY is required" in script
