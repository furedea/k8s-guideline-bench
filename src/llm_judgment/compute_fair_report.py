"""CLI for computing a fair-summary report from existing judgments + gold scope.

Usage:
    uv run python src/llm_judgment/compute_fair_report.py --spec config/experiment_spec_pilot.json

Reads existing per-instance ``judgments.json`` files plus the persisted
gold-scope (``<results_root>/gold_scope/<instance>/judgments.json``) and emits
``<results_root>/fair_report.json``: one ``FairJudgmentSummary`` per agent run
sharing the same gold-scope denominator. Idempotent and read-only against
agent runs (no LLM calls), so it can be replayed any time scope changes.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stage in ("llm_judgment", "agent_execution", "dataset_construction", "constraint_extraction", "common", ""):
    sys.path.insert(0, str(ROOT / "src" / _stage))

import base  # noqa: E402
import experiment  # noqa: E402
import fair_summary  # noqa: E402
import gold_scope  # noqa: E402
import judge  # noqa: E402
import project_paths  # noqa: E402
import pydantic  # noqa: E402

SCOPED_JUDGE_RUN_SUFFIX = "__gold_scope"


class FairReport(base.FrozenModel):
    """Top-level fair-summary report keyed by ``results_root``."""

    results_root: Path
    runs: tuple[fair_summary.FairJudgmentSummary, ...]

    @pydantic.field_validator("runs", mode="before")
    @classmethod
    def validate_runs(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the fair-summary post-processor."""
    parser = argparse.ArgumentParser(description="Compute a fair-summary report from existing judgments.")
    _ = parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to the experiment spec JSON.",
    )
    _ = parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Project root used to resolve relative paths in the spec.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: load spec → enumerate run_ids → emit fair_report.json."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    arguments = parse_args()
    spec = experiment.load_experiment_spec(arguments.spec)
    results_root = project_paths.resolve_under(arguments.project_root, spec.results_root)
    run_ids = tuple(agent_config.run_id for agent_config in spec.agent_configs)
    report = compute_fair_report(results_root=results_root, run_ids=run_ids)
    print(render_report(report), end="")


def compute_fair_report(
    *,
    results_root: Path,
    run_ids: tuple[str, ...],
) -> FairReport:
    """Read per-instance judgments + gold scope, return the aggregated fair report.

    Persists ``<results_root>/fair_report.json`` so downstream tools can read
    the report without re-running this command.
    """
    scope = gold_scope.load_gold_scope(results_root)
    existing_scope = gold_scope.load_existing_rule_scope(results_root)
    runs = tuple(
        fair_summary.summarize_with_scope(
            run_id=run_id,
            run_judgments=_load_run_judgments(results_root, run_id=run_id),
            scope=scope,
            existing_scope=existing_scope,
        )
        for run_id in run_ids
    )
    report = FairReport(results_root=results_root, runs=runs)
    _persist_report(report)
    return report


def render_report(report: FairReport) -> str:
    """Render a per-PR hits/scope table for every run."""
    sections = tuple(_render_run_summary(run_summary) for run_summary in report.runs)
    return "\n".join(sections)


def _render_run_summary(run_summary: fair_summary.FairJudgmentSummary) -> str:
    lines = [
        f"=== {run_summary.run_id} ===",
        _render_table_row("PR", "new_rules", "lost_existing", "extra_new", "eval_error"),
    ]
    lines.extend(_render_instance_score(score) for score in run_summary.instance_scores)
    lost_existing = sum(score.lost_existing_rules for score in run_summary.instance_scores)
    extra_new = sum(score.extra_newly_satisfied for score in run_summary.instance_scores)
    eval_error = sum(score.eval_error for score in run_summary.instance_scores)
    lines.append(
        _render_table_row(
            "total",
            f"{run_summary.newly_satisfied}/{run_summary.common_scope_total}",
            str(lost_existing),
            str(extra_new),
            str(eval_error),
        ),
    )
    lines.append("")
    return "\n".join(lines)


def _render_instance_score(score: fair_summary.FairInstanceScore) -> str:
    new_rules = f"{score.newly_satisfied}/{score.scope_total}" if score.scope_total else "-/0"
    return _render_table_row(
        score.instance_id,
        new_rules,
        str(score.lost_existing_rules),
        str(score.extra_newly_satisfied),
        str(score.eval_error),
    )


def _render_table_row(
    pr: str,
    new_rules: str,
    lost_existing: str,
    extra_new: str,
    eval_error: str,
) -> str:
    return f"{pr:<7} {new_rules:<10} {lost_existing:<14} {extra_new:<10} {eval_error}"


def _load_run_judgments(results_root: Path, run_id: str) -> tuple[judge.InstanceJudgment, ...]:
    source_run_id = _judgment_source_run_id(results_root, run_id)
    run_dir = results_root / source_run_id
    if not run_dir.is_dir():
        return ()
    loaded: list[judge.InstanceJudgment] = []
    for instance_dir in sorted(run_dir.iterdir()):
        if not instance_dir.is_dir():
            continue
        if not (instance_dir / "judgments.json").is_file():
            continue
        judgments = judge.load_instance_judgments(results_root, source_run_id, instance_dir.name)
        if not judgments:
            continue
        loaded.append(
            judge.InstanceJudgment(
                instance_id=instance_dir.name,
                run_id=run_id,
                judgments=judgments,
            ),
        )
    return tuple(loaded)


def _judgment_source_run_id(results_root: Path, run_id: str) -> str:
    scoped_run_id = f"{run_id}{SCOPED_JUDGE_RUN_SUFFIX}"
    if (results_root / scoped_run_id).is_dir():
        return scoped_run_id
    return run_id


def _persist_report(report: FairReport) -> None:
    report.results_root.mkdir(parents=True, exist_ok=True)
    _ = (report.results_root / "fair_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
