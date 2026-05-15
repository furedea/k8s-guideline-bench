#!/usr/bin/env python3
"""Inspect agent run artifacts produced by the benchmark runner."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BYTES_PER_TOKEN_ESTIMATE = 4
METADATA_FILENAME = "run_metadata.json"
SETTINGS_FILENAME = "mini_swe_agent_settings.env"
TRAJECTORY_FILENAME = "trajectory.json"
STDOUT_FILENAME = "mini_swe_agent_stdout.log"
STDERR_FILENAME = "mini_swe_agent_stderr.log"


@dataclass(frozen=True, slots=True)
class AgentRunInspection:
    path: Path
    run_id: str
    pr_number: str
    status: str
    failure_reason: str
    duration_seconds: float | None
    exit_code: int | None
    predicted_patch_bytes: int
    step_limit: str
    api_calls: int | None
    exit_status: str
    message_count: int | None
    estimated_context_tokens: int | None
    largest_message_tokens: int | None
    largest_message_role: str
    trajectory_bytes: int
    stdout_bytes: int
    stderr_bytes: int


def inspect_paths(paths: Sequence[Path]) -> tuple[AgentRunInspection, ...]:
    run_dirs = tuple(_iter_run_dirs(paths))
    return tuple(inspect_run_dir(run_dir) for run_dir in sorted(run_dirs))


def inspect_run_dir(run_dir: Path) -> AgentRunInspection:
    metadata = _load_json(run_dir / METADATA_FILENAME)
    settings = _load_settings(run_dir / SETTINGS_FILENAME)
    trajectory = _load_optional_json(run_dir / TRAJECTORY_FILENAME)
    trajectory_summary = _summarize_trajectory(trajectory)

    return AgentRunInspection(
        path=run_dir,
        run_id=run_dir.parent.name,
        pr_number=str(metadata.get("pr_number", run_dir.name)),
        status=str(metadata.get("status", "unknown")),
        failure_reason=str(metadata.get("failure_reason") or "-"),
        duration_seconds=_optional_float(metadata.get("duration_seconds")),
        exit_code=_optional_int(metadata.get("exit_code")),
        predicted_patch_bytes=_int_or_zero(metadata.get("predicted_patch_bytes")),
        step_limit=settings.get("step_limit", "-"),
        api_calls=trajectory_summary.api_calls,
        exit_status=trajectory_summary.exit_status,
        message_count=trajectory_summary.message_count,
        estimated_context_tokens=trajectory_summary.estimated_context_tokens,
        largest_message_tokens=trajectory_summary.largest_message_tokens,
        largest_message_role=trajectory_summary.largest_message_role,
        trajectory_bytes=_file_size(run_dir / TRAJECTORY_FILENAME),
        stdout_bytes=_file_size(run_dir / STDOUT_FILENAME),
        stderr_bytes=_file_size(run_dir / STDERR_FILENAME),
    )


def format_inspections(inspections: Sequence[AgentRunInspection]) -> str:
    rows = [
        (
            inspection.run_id,
            inspection.pr_number,
            inspection.status,
            inspection.failure_reason,
            _format_float(inspection.duration_seconds),
            _format_optional_int(inspection.exit_code),
            str(inspection.predicted_patch_bytes),
            inspection.step_limit,
            _format_optional_int(inspection.api_calls),
            inspection.exit_status or "-",
            _format_optional_int(inspection.message_count),
            _format_optional_int(inspection.estimated_context_tokens),
            _format_optional_int(inspection.largest_message_tokens),
            inspection.largest_message_role,
            str(inspection.trajectory_bytes),
            str(inspection.stderr_bytes),
        )
        for inspection in inspections
    ]
    return _format_table(
        (
            "run_id",
            "pr",
            "status",
            "reason",
            "sec",
            "exit",
            "patch_B",
            "step_limit",
            "calls",
            "agent_exit",
            "messages",
            "ctx_est",
            "max_msg",
            "max_role",
            "traj_B",
            "stderr_B",
        ),
        rows,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect benchmark agent run artifacts.")
    parser.add_argument("paths", nargs="+", type=Path, help="run directory or results root")
    parser.add_argument("--latest", type=int, default=0, help="only print the latest N runs by metadata mtime")
    parser.add_argument("--tail", type=int, default=0, help="print the last N stderr/stdout lines for each run")
    parser.add_argument("--top-messages", type=int, default=0, help="print the N largest trajectory messages")
    args = parser.parse_args(argv)

    inspections = inspect_paths(args.paths)
    if args.latest > 0:
        inspections = tuple(
            sorted(inspections, key=lambda inspection: _metadata_mtime(inspection.path), reverse=True)[: args.latest]
        )
    print(format_inspections(inspections))
    if args.top_messages > 0:
        for inspection in inspections:
            _print_top_messages(inspection.path, args.top_messages)
    if args.tail > 0:
        for inspection in inspections:
            _print_tail(inspection.path, args.tail)
    return 0


@dataclass(frozen=True, slots=True)
class _TrajectorySummary:
    api_calls: int | None
    exit_status: str
    message_count: int | None
    estimated_context_tokens: int | None
    largest_message_tokens: int | None
    largest_message_role: str


def _iter_run_dirs(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if (path / METADATA_FILENAME).exists():
            yield path
            continue
        yield from (metadata_path.parent for metadata_path in path.rglob(METADATA_FILENAME))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def _load_settings(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    settings: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            settings[key] = value
    return settings


def _summarize_trajectory(trajectory: dict[str, Any] | None) -> _TrajectorySummary:
    if trajectory is None:
        return _TrajectorySummary(
            api_calls=None,
            exit_status="-",
            message_count=None,
            estimated_context_tokens=None,
            largest_message_tokens=None,
            largest_message_role="-",
        )
    info = trajectory.get("info") if isinstance(trajectory.get("info"), dict) else {}
    model_stats = info.get("model_stats") if isinstance(info.get("model_stats"), dict) else {}
    messages = trajectory.get("messages") if isinstance(trajectory.get("messages"), list) else []
    largest_message = _largest_message(messages)
    return _TrajectorySummary(
        api_calls=_optional_int(model_stats.get("api_calls")),
        exit_status=str(info.get("exit_status") or "-"),
        message_count=len(messages),
        estimated_context_tokens=_estimate_context_tokens(messages),
        largest_message_tokens=largest_message.estimated_tokens,
        largest_message_role=largest_message.role,
    )


def _estimate_context_tokens(messages: Sequence[Any]) -> int:
    characters = sum(len(_message_content(message)) for message in messages)
    return characters // BYTES_PER_TOKEN_ESTIMATE


@dataclass(frozen=True, slots=True)
class _MessageSize:
    index: int
    role: str
    characters: int
    estimated_tokens: int
    preview: str


def _largest_message(messages: Sequence[Any]) -> _MessageSize:
    sizes = _message_sizes(messages)
    if not sizes:
        return _MessageSize(index=-1, role="-", characters=0, estimated_tokens=0, preview="")
    return max(sizes, key=lambda size: size.characters)


def _message_sizes(messages: Sequence[Any]) -> tuple[_MessageSize, ...]:
    sizes: list[_MessageSize] = []
    for index, message in enumerate(messages):
        content = _message_content(message)
        sizes.append(
            _MessageSize(
                index=index,
                role=_message_role(message),
                characters=len(content),
                estimated_tokens=len(content) // BYTES_PER_TOKEN_ESTIMATE,
                preview=_message_preview(content),
            )
        )
    return tuple(sizes)


def _message_role(message: Any) -> str:
    if not isinstance(message, dict):
        return "-"
    role = message.get("role")
    return role if isinstance(role, str) else "-"


def _message_content(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False) if content is not None else ""


def _message_preview(content: str) -> str:
    first_line = content.strip().splitlines()
    if not first_line:
        return ""
    return first_line[0][:120]


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _metadata_mtime(run_dir: Path) -> float:
    metadata_path = run_dir / METADATA_FILENAME
    return metadata_path.stat().st_mtime if metadata_path.exists() else 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _int_or_zero(value: Any) -> int:
    return _optional_int(value) or 0


def _format_float(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _format_optional_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def _format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row, strict=True)]
    lines = [_format_table_row(headers, widths), _format_table_row(tuple("-" * width for width in widths), widths)]
    lines.extend(_format_table_row(row, widths) for row in rows)
    return "\n".join(lines)


def _format_table_row(row: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True))


def _print_tail(run_dir: Path, line_count: int) -> None:
    print()
    print(f"== {run_dir} ==")
    for filename in (STDERR_FILENAME, STDOUT_FILENAME):
        path = run_dir / filename
        print(f"-- {filename} --")
        if not path.exists():
            print("(missing)")
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-line_count:]))


def _print_top_messages(run_dir: Path, message_count: int) -> None:
    trajectory = _load_optional_json(run_dir / TRAJECTORY_FILENAME)
    if trajectory is None:
        return
    messages = trajectory.get("messages") if isinstance(trajectory.get("messages"), list) else []
    sizes = sorted(_message_sizes(messages), key=lambda size: size.characters, reverse=True)[:message_count]
    print()
    print(f"== {run_dir} top messages ==")
    for size in sizes:
        print(f"{size.index}\t{size.role}\t{size.characters} chars\t~{size.estimated_tokens} tokens\t{size.preview}")


if __name__ == "__main__":
    raise SystemExit(main())
