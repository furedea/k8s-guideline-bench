# Local Agent Operations

This project can run local OpenAI-compatible models through the Docker agent backend. The current local-100 setup uses Qwen3.6 FP8 served by SGLang and mini-SWE-agent as the editing scaffold.

## Server Processes

The local model stack uses a dedicated Docker network:

- `k8s-bench-llm`: SGLang model server.
- `k8s-bench-proxy`: Qwen non-thinking proxy.
- `k8s-bench-local`: internal Docker network used by the model, proxy, and agent containers.

Only the proxy is exposed to the host on `127.0.0.1:8002`. Agent containers reach the same proxy at `http://k8s-bench-proxy:8002/v1`. This keeps agent execution off `--network=host`, while preserving host-side access for smoke checks and judgment.

The model weights must already be present under `~/.cache/huggingface` before starting this isolated stack. The internal Docker network intentionally prevents the model and agent containers from reaching external sites.

Start the local stack in one tmux pane:

```bash
docker compose -f docker-compose.local-llm.yml up --build
```

The compose file is tuned for lecun's two RTX 3090 GPUs with tensor parallelism:

- `--tp ${LOCAL_LLM_TP:-2}`
- `--disable-custom-all-reduce`
- `--context-length 65536`
- `--mem-fraction-static 0.82`
- `--tool-call-parser qwen3_coder`

On a single-GPU server such as sam, start the stack with `LOCAL_LLM_TP=1`:

```bash
LOCAL_LLM_TP=1 docker compose -f docker-compose.local-llm.yml up --build
```

## Agent Image

Rebuild after changes under `docker/`:

```bash
docker build --no-cache \
  -t k8s-bench-agent-mini-swe-agent \
  -f docker/Dockerfile.mini_swe_agent .
```

Verify the image:

```bash
docker run --rm k8s-bench-agent-mini-swe-agent \
  sh -lc 'command -v mini && command -v run-mini-swe-agent && mini --help >/dev/null'
```

Verify host-side proxy access:

```bash
curl http://localhost:8002/v1/chat/completions \
  -H "Authorization: Bearer ${LOCAL_LLM_API_KEY:?LOCAL_LLM_API_KEY is required}" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3.6-27B-FP8","messages":[{"role":"user","content":"Return JSON only:{\"ok\":true}"}],"max_tokens":64}'
```

Verify agent-network proxy access:

```bash
docker run --rm --network k8s-bench-local \
  --env LOCAL_LLM_API_KEY \
  k8s-bench-agent-mini-swe-agent \
  /opt/mini-swe-agent/bin/python - http://k8s-bench-proxy:8002/v1 Qwen/Qwen3.6-27B-FP8 <<'PY'
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
```

## Smoke Test

Use the smoke script for the one-PR agent check. It intentionally runs only the agent stage, not gold scope or judgment:

```bash
export MINI_SWE_AGENT_STEP_LIMIT=20
scripts/smoke_local_agent.sh config/experiment_spec_local_100.json 1
```

The local config uses:

- `run_id_prefix`: `local100_mini_qwen36_fp8`
- `context_limit`: `65536`
- agent base URL: `http://k8s-bench-proxy:8002/v1`
- judge base URL: `http://localhost:8002/v1`
- agent Docker network: `k8s-bench-local`
- `agent_timeout_seconds`: `2400`
- `MINI_SWE_AGENT_STEP_LIMIT`: defaults to `20`
- `MINI_SWE_AGENT_COST_LIMIT`: optional mini-SWE-agent cost cap, unset by default

The experiment spec names `LOCAL_LLM_API_KEY` as the local model credential. The runner passes that environment variable and `MINI_SWE_AGENT_AUTH_ENV=LOCAL_LLM_API_KEY` into the agent container. The wrapper then maps the configured credential into `OPENAI_API_KEY` inside the container, which is what LiteLLM expects.

The wrapper resolves mini-SWE-agent's bundled `mini.yaml`, writes `/out/mini_runtime.yaml` with `agent.step_limit` already applied, and passes only that generated file to `-c`. This avoids relying on Typer's repeated `-c` parsing or mini-SWE-agent's config-name lookup on different package versions. Runtime config generation uses `/opt/mini-swe-agent/bin/python` so it runs in the same virtual environment as the `mini` executable and can import mini-SWE-agent's YAML dependencies.

After agent smoke passes, run the later stages separately:

```bash
uv run python src/llm_judgment/run_gold_scope.py \
  --spec config/experiment_spec_local_100.json \
  --limit 1

uv run python src/llm_judgment/run_judgment.py \
  --spec config/experiment_spec_local_100.json \
  --limit 1

uv run python src/llm_judgment/compute_fair_report.py \
  --spec config/experiment_spec_local_100.json
```

## Failure Debugging

Each agent result directory should contain:

```text
raw_response.txt
run_metadata.json
agent_execution_config.json
prompt.txt
mini_swe_agent_stdout.log
mini_swe_agent_stderr.log
mini_swe_agent_settings.env
mini_runtime.yaml
trajectory.json
```

Inspect a failed run:

```bash
d=results/local_100/<run_id>/<pr_number>
uv run python scripts/inspect_agent_run.py "$d" --top-messages 5 --tail 80
sed -n '1,120p' "$d/run_metadata.json"
sed -n '1,120p' "$d/agent_execution_config.json"
sed -n '1,80p' "$d/mini_swe_agent_settings.env"
sed -n '1,160p' "$d/mini_runtime.yaml"
tail -200 "$d/mini_swe_agent_stderr.log"
tail -200 "$d/mini_swe_agent_stdout.log"
test -f "$d/trajectory.json" && wc -c "$d/trajectory.json"
```

Common `failure_reason` values:

- `timeout`: the outer Docker agent timeout fired.
- `agent_budget_exceeded`: mini-SWE-agent hit its step or cost budget.
- `context_window_exceeded`: the model context window was exceeded.
- `external_network_access`: mini-SWE-agent attempted to fetch external network resources during the run.
- `empty_patch`: the agent exited successfully but produced no diff.
- `bad_request`, `rate_limited`, `agent_reported_error`, `agent_error`: API or scaffold failures.

If a run times out, Docker cleanup is attempted using a deterministic container name. Check for leftovers with:

```bash
docker ps --format '{{.ID}} {{.Image}} {{.Names}} {{.Command}}' | grep k8s-bench-agent
```

For a compact overview of all local runs:

```bash
uv run python scripts/inspect_agent_run.py results/local_100
uv run python scripts/inspect_agent_run.py results/local_100 --latest 9
```

`ctx_est` and `max_msg` are rough token estimates based on saved trajectory text. They are not tokenizer-exact, but they are enough to detect whether a run is burning context on large command output or repeated history.
