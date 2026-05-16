#!/bin/bash
set -euxCo pipefail
cd "$(dirname "$0")"

function usage() {
  cat <<EOF >&2
Description:
    Smoke-test the local mini-SWE-agent backend without running judgment.

Usage:
    $0 [SPEC_PATH] [LIMIT]

Defaults:
    SPEC_PATH: config/experiment_spec_local_100.json
    LIMIT: 1
EOF
  exit 1
}

function read_spec_values() {
  local _spec_path="$1"
  uv run python - "${_spec_path}" <<'PY'
import json
import sys
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
matrix = spec["agent_matrix"]
docker = matrix["docker"]
provider = matrix["docker"]["openai_compatible_provider"]
agent_network = next(
    (arg.split("=", 1)[1] for arg in docker.get("docker_args", []) if arg.startswith("--network=")),
    "",
)

print(provider["client"]["base_url"].rstrip("/"))
print(spec["judge_config"]["client"]["base_url"].rstrip("/"))
print(matrix["models"][0])
print(spec["results_root"])
print(agent_network)
print(docker["image"])
PY
}

function main() {
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
  fi
  if [[ "$#" -gt 2 ]]; then
    usage
  fi

  local -r _repo_root="$(cd .. && pwd)"
  cd "${_repo_root}"

  local -r _spec_path="${1:-config/experiment_spec_local_100.json}"
  local -r _limit="${2:-1}"
  if [[ ! -f "${_spec_path}" ]]; then
    echo "spec not found: ${_spec_path}" >&2
    exit 2
  fi

  local -a _spec_values
  mapfile -t _spec_values < <(read_spec_values "${_spec_path}")
  local -r _agent_base_url="${_spec_values[0]}"
  local -r _host_base_url="${_spec_values[1]}"
  local -r _model="${_spec_values[2]}"
  local -r _results_root="${_spec_values[3]}"
  local -r _agent_network="${_spec_values[4]}"
  local -r _agent_image="${_spec_values[5]}"

  echo "== config =="
  grep -n '"run_id_prefix"\|"models"\|"model"\|"base_url"\|"context_limit"\|"output_limit"\|"agent_timeout_seconds"' \
    "${_spec_path}" || true

  echo "== docker image =="
  docker run --rm k8s-bench-agent-mini-swe-agent \
    sh -lc 'command -v mini && command -v run-mini-swe-agent'
  docker run --rm -i k8s-bench-agent-mini-swe-agent \
    /opt/mini-swe-agent/bin/python - <<'PY'
from minisweagent.config import builtin_config_dir

import yaml

yaml.safe_load((builtin_config_dir / "mini.yaml").read_text(encoding="utf-8"))
PY

  echo "== host local endpoint =="
  set +x
  curl "${_host_base_url}/chat/completions" \
    -H "Authorization: Bearer ${LOCAL_LLM_API_KEY:?LOCAL_LLM_API_KEY is required}" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\":\"${_model}\",
      \"messages\":[{\"role\":\"user\",\"content\":\"Return JSON only:{\\\"ok\\\":true}\"}],
      \"max_tokens\":64
    }"
  set -x
  echo

  echo "== agent-network local endpoint =="
  docker run --rm --network "${_agent_network}" \
    --env LOCAL_LLM_API_KEY \
    "${_agent_image}" \
    /opt/mini-swe-agent/bin/python - "${_agent_base_url}" "${_model}" <<'PY'
import json
import os
import sys
import urllib.request

base_url = sys.argv[1]
model = sys.argv[2]
payload = {
    "model": model,
    "messages": [{"role": "user", "content": 'Return JSON only:{"ok":true}'}],
    "max_tokens": 64,
}
request = urllib.request.Request(
    f"{base_url}/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {os.environ['LOCAL_LLM_API_KEY']}",
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=60) as response:
    print(response.read().decode("utf-8"))
PY

  echo "== agent =="
  uv run python src/agent_execution/run_agent.py \
    --spec "${_spec_path}" \
    --limit "${_limit}"

  echo "== recent agent artifacts =="
  uv run python scripts/inspect_agent_run.py "${_results_root}" --latest 9
}

main "$@"
