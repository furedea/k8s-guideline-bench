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

  : "${OPENAI_API_KEY:?OPENAI_API_KEY is required by LiteLLM}"

  cd "${WORKTREE}"
  MSWEA_CONFIGURED=1 mini \
    --agent-class default \
    --exit-immediately \
    -y \
    -m "${MODEL_NAME}" \
    -t "$(cat "${PROMPT_PATH}")"
}

main "$@"
