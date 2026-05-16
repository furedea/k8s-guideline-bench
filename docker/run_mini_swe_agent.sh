#!/bin/bash
set -euxCo pipefail
cd "$(dirname "$0")"

function usage() {
  cat <<EOF >&2
Description:
    Run mini-SWE-agent against the mounted benchmark worktree.

Usage:
    $0
EOF
  exit 1
}

function main() {
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
  fi
  if [[ "$#" -ne 0 ]]; then
    usage
  fi

  readonly PROMPT_PATH="${AGENT_PROMPT_PATH:?AGENT_PROMPT_PATH is required}"
  readonly MODEL_NAME="${MODEL:?MODEL is required}"
  readonly WORKTREE="${WORKTREE_PATH:-/work}"
  readonly OUTPUT_DIR="${OUTPUT_PATH:-/out}"
  readonly STEP_LIMIT="${MINI_SWE_AGENT_STEP_LIMIT:-20}"
  readonly COST_LIMIT="${MINI_SWE_AGENT_COST_LIMIT:-}"
  readonly COST_TRACKING="${MINI_SWE_AGENT_COST_TRACKING:-ignore_errors}"
  readonly TOOL_CHOICE="${MINI_SWE_AGENT_TOOL_CHOICE:-required}"
  readonly TRAJECTORY_PATH="${MINI_SWE_AGENT_TRAJECTORY_PATH:-${OUTPUT_DIR}/trajectory.json}"
  readonly AUTH_ENV_NAME="${MINI_SWE_AGENT_AUTH_ENV:-}"
  readonly MINI_PYTHON="${MINI_SWE_AGENT_PYTHON:-/opt/mini-swe-agent/bin/python}"
  readonly MINI_CONFIG_SOURCE_PATH="${MINI_SWE_AGENT_CONFIG_PATH:-$(
    "${MINI_PYTHON}" - <<'PY'
import contextlib
import sys

with contextlib.redirect_stdout(sys.stderr):
    from minisweagent.config import builtin_config_dir

sys.stdout.write(str(builtin_config_dir / "mini.yaml"))
PY
  )}"
  readonly MINI_RUNTIME_CONFIG_PATH="${OUTPUT_DIR}/mini_runtime.yaml"

  if [[ -n "${AUTH_ENV_NAME}" ]]; then
    local _credential="${!AUTH_ENV_NAME:-}"
    if [[ -n "${_credential}" ]]; then
      printf -v OPENAI_API_KEY "%s" "${_credential}"
      export OPENAI_API_KEY
    fi
  fi
  : "${OPENAI_API_KEY:?OPENAI_API_KEY is required by LiteLLM}"

  mkdir -p "${OUTPUT_DIR}" "$(dirname "${TRAJECTORY_PATH}")"
  : >|"${OUTPUT_DIR}/mini_swe_agent_stdout.log"
  : >|"${OUTPUT_DIR}/mini_swe_agent_stderr.log"
  exec > >(tee -a "${OUTPUT_DIR}/mini_swe_agent_stdout.log")
  exec 2> >(tee -a "${OUTPUT_DIR}/mini_swe_agent_stderr.log" >&2)
  "${MINI_PYTHON}" - "${MINI_CONFIG_SOURCE_PATH}" "${MINI_RUNTIME_CONFIG_PATH}" "${STEP_LIMIT}" "${COST_TRACKING}" "${TOOL_CHOICE}" <<'PY'
import sys
from pathlib import Path

import yaml

source_path = Path(sys.argv[1])
runtime_path = Path(sys.argv[2])
step_limit = int(sys.argv[3])
cost_tracking = sys.argv[4]
tool_choice = sys.argv[5]

config = yaml.safe_load(source_path.read_text()) or {}
config.setdefault("agent", {})["step_limit"] = step_limit
config.setdefault("model", {})["cost_tracking"] = cost_tracking
config.setdefault("model", {}).setdefault("model_kwargs", {})["tool_choice"] = tool_choice
runtime_path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
  {
    echo "model=${MODEL_NAME}"
    echo "worktree=${WORKTREE}"
    echo "prompt_path=${PROMPT_PATH}"
    echo "python=${MINI_PYTHON}"
    echo "config_source=${MINI_CONFIG_SOURCE_PATH}"
    echo "runtime_config=${MINI_RUNTIME_CONFIG_PATH}"
    echo "auth_env=${AUTH_ENV_NAME}"
    echo "step_limit=${STEP_LIMIT}"
    echo "cost_limit=${COST_LIMIT}"
    echo "cost_tracking=${COST_TRACKING}"
    echo "tool_choice=${TOOL_CHOICE}"
    echo "trajectory_path=${TRAJECTORY_PATH}"
  } >|"${OUTPUT_DIR}/mini_swe_agent_settings.env"

  local -a _mini_args=(
    --agent-class default
    --exit-immediately
    -y
    -m "${MODEL_NAME}"
    -c "${MINI_RUNTIME_CONFIG_PATH}"
    -o "${TRAJECTORY_PATH}"
  )
  if [[ -n "${COST_LIMIT}" ]]; then
    _mini_args+=(-l "${COST_LIMIT}")
  fi

  cd "${WORKTREE}"
  set +x
  MSWEA_CONFIGURED=1 mini "${_mini_args[@]}" -t "$(cat "${PROMPT_PATH}")"
  set -x
}

main "$@"
