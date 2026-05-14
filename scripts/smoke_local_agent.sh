#!/usr/bin/env bash
set -euo pipefail

SPEC_PATH="${1:-config/experiment_spec_local_100.json}"
LIMIT="${2:-1}"

if [[ ! -f "${SPEC_PATH}" ]]; then
  echo "spec not found: ${SPEC_PATH}" >&2
  exit 2
fi

echo "== config =="
grep -n '"run_id_prefix"\|"models"\|"model"\|"base_url"\|"context_limit"\|"output_limit"\|"agent_timeout_seconds"' "${SPEC_PATH}" || true

echo "== docker image =="
docker run --rm k8s-bench-agent-mini-swe-agent \
  sh -lc 'command -v mini && command -v run-mini-swe-agent && mini --help >/dev/null'

echo "== local endpoint =="
BASE_URL="$(grep -m1 '"base_url"' "${SPEC_PATH}" | sed -E 's/.*"base_url": "([^"]+)".*/\1/')"
MODEL="$(grep -m1 -A2 '"models"' "${SPEC_PATH}" | grep '"' | tail -1 | sed -E 's/.*"([^"]+)".*/\1/')"
curl "${BASE_URL}/chat/completions" \
  -H "Authorization: Bearer ${LOCAL_LLM_API_KEY:?LOCAL_LLM_API_KEY is required}" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Return JSON only:{\\\"ok\\\":true}\"}],\"max_tokens\":64}"
echo

echo "== experiment =="
uv run python src/llm_judgment/run_experiment.py \
  --spec "${SPEC_PATH}" \
  --limit "${LIMIT}"

echo "== recent local_100 artifacts =="
find results/local_100 -path '*/run_metadata.json' -print0 |
  xargs -0 ls -t |
  head -9 |
  while read -r metadata; do
    dir="$(dirname "${metadata}")"
    echo "--- ${dir} ---"
    sed -n '1,80p' "${metadata}"
    test -f "${dir}/mini_swe_agent_settings.env" && sed -n '1,40p' "${dir}/mini_swe_agent_settings.env"
    test -f "${dir}/trajectory.json" && wc -c "${dir}/trajectory.json"
  done
