# Local Agent Operations

This project can run local OpenAI-compatible models through the Docker agent backend. The current local-100 setup is tuned for sam with Qwen3.6 FP8 served by SGLang and mini-SWE-agent as the editing scaffold.

## Server Processes

Run the model server in one tmux pane:

```bash
docker run --rm --gpus all \
  --ipc=host \
  --shm-size 32g \
  --network=host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e HF_TOKEN="$HF_TOKEN" \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server \
    --model-path Qwen/Qwen3.6-27B-FP8 \
    --served-model-name Qwen/Qwen3.6-27B-FP8 \
    --host 0.0.0.0 \
    --port 8001 \
    --api-key "$LOCAL_LLM_API_KEY" \
    --context-length 65536 \
    --mem-fraction-static 0.82
```

Run the Qwen non-thinking proxy in another pane:

```bash
uv run python src/local_llm_proxy.py \
  --upstream http://localhost:8001/v1 \
  --host 127.0.0.1 \
  --port 8002
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

## Smoke Test

Use the smoke script for the one-PR check:

```bash
export MINI_SWE_AGENT_STEP_LIMIT=20
scripts/smoke_local_agent.sh config/experiment_spec_local_100.json 1
```

The local config uses:

- `run_id_prefix`: `local100_mini_qwen36_fp8`
- `context_limit`: `65536`
- `agent_timeout_seconds`: `2400`
- `MINI_SWE_AGENT_STEP_LIMIT`: defaults to `20`
- `MINI_SWE_AGENT_COST_LIMIT`: optional mini-SWE-agent cost cap, unset by default

The wrapper passes `-c mini.yaml` before `-c agent.step_limit=...`. mini-SWE-agent does not load its default config once any `-c` option is supplied, so the base config must stay explicit.

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
trajectory.json
```

Inspect a failed run:

```bash
d=results/local_100/<run_id>/<pr_number>
uv run python scripts/inspect_agent_run.py "$d" --top-messages 5 --tail 80
sed -n '1,120p' "$d/run_metadata.json"
sed -n '1,120p' "$d/agent_execution_config.json"
sed -n '1,80p' "$d/mini_swe_agent_settings.env"
tail -200 "$d/mini_swe_agent_stderr.log"
tail -200 "$d/mini_swe_agent_stdout.log"
test -f "$d/trajectory.json" && wc -c "$d/trajectory.json"
```

Common `failure_reason` values:

- `timeout`: the outer Docker agent timeout fired.
- `agent_budget_exceeded`: mini-SWE-agent hit its step or cost budget.
- `context_window_exceeded`: the model context window was exceeded.
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
