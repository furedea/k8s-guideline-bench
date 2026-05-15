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
  readonly TRAJECTORY_PATH="${MINI_SWE_AGENT_TRAJECTORY_PATH:-${OUTPUT_DIR}/trajectory.json}"

  : "${OPENAI_API_KEY:?OPENAI_API_KEY is required by LiteLLM}"

  mkdir -p "${OUTPUT_DIR}" "$(dirname "${TRAJECTORY_PATH}")"
  exec > >(tee -a "${OUTPUT_DIR}/mini_swe_agent_stdout.log")
  exec 2> >(tee -a "${OUTPUT_DIR}/mini_swe_agent_stderr.log" >&2)
  {
    echo "model=${MODEL_NAME}"
    echo "worktree=${WORKTREE}"
    echo "prompt_path=${PROMPT_PATH}"
    echo "config=mini.yaml"
    echo "step_limit=${STEP_LIMIT}"
    echo "cost_limit=${COST_LIMIT}"
    echo "trajectory_path=${TRAJECTORY_PATH}"
  } >"${OUTPUT_DIR}/mini_swe_agent_settings.env"

  local -a _mini_args=(
    --agent-class default
    --exit-immediately
    -y
    -m "${MODEL_NAME}"
    -c mini.yaml "agent.step_limit=${STEP_LIMIT}"
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
