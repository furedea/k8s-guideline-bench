"""Static checks for benchmark agent Docker images."""

import json
import shlex
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

IMAGE_DOCKERFILES = {
    "k8s-bench-agent": REPO_ROOT / "docker" / "Dockerfile",
    "k8s-bench-agent-mini-swe-agent": REPO_ROOT / "docker" / "Dockerfile.mini_swe_agent",
}

IMAGE_COMMAND_PROVISIONS = {
    "k8s-bench-agent": ("opencode",),
    "k8s-bench-agent-mini-swe-agent": ("run-mini-swe-agent", "mini", "mini-extra"),
}


def test_experiment_specs_reference_known_agent_images() -> None:
    for spec_path in sorted((REPO_ROOT / "config").glob("experiment_spec*.json")):
        spec = _load_json(spec_path)

        for docker_config in _iter_docker_configs(spec):
            image = docker_config["image"]

            assert image in IMAGE_DOCKERFILES, f"{spec_path} references unknown Docker image {image!r}"
            assert IMAGE_DOCKERFILES[image].exists(), f"{image!r} has no Dockerfile"


def test_agent_dockerfiles_provide_configured_commands() -> None:
    for spec_path in sorted((REPO_ROOT / "config").glob("experiment_spec*.json")):
        spec = _load_json(spec_path)

        for docker_config in _iter_docker_configs(spec):
            image = docker_config["image"]
            command = _first_shell_token(docker_config["agent_command"])
            dockerfile = IMAGE_DOCKERFILES[image]
            dockerfile_text = dockerfile.read_text()

            assert command in IMAGE_COMMAND_PROVISIONS[image], (
                f"{spec_path} configures {command!r} for {image!r}, but the image provision list does not include it"
            )
            assert _dockerfile_mentions_command(dockerfile_text, command), (
                f"{dockerfile} does not visibly provide configured command {command!r}"
            )


def test_mini_swe_agent_wrapper_dependencies_are_provided_by_image() -> None:
    dockerfile_text = (REPO_ROOT / "docker" / "Dockerfile.mini_swe_agent").read_text()
    wrapper_text = (REPO_ROOT / "docker" / "run_mini_swe_agent.sh").read_text()

    assert "mini-swe-agent" in dockerfile_text
    assert "/usr/local/bin/mini" in dockerfile_text
    assert "mini --help" in dockerfile_text
    assert "/opt/mini-swe-agent/bin/python" in dockerfile_text
    assert "import yaml" in dockerfile_text
    assert 'builtin_config_dir / "mini.yaml"' in dockerfile_text
    assert "MSWEA_CONFIGURED=1 mini" in wrapper_text
    assert "--agent-class default" in wrapper_text
    assert "--exit-immediately" in wrapper_text
    assert "MINI_SWE_AGENT_STEP_LIMIT" in wrapper_text
    assert "MINI_SWE_AGENT_COST_LIMIT" in wrapper_text
    assert "MINI_SWE_AGENT_COST_TRACKING" in wrapper_text
    assert "ignore_errors" in wrapper_text
    assert "MINI_SWE_AGENT_TOOL_CHOICE" in wrapper_text
    assert "required" in wrapper_text
    assert "MINI_SWE_AGENT_AUTH_ENV" in wrapper_text
    assert "printf -v OPENAI_API_KEY" in wrapper_text
    assert "export OPENAI_API_KEY" in wrapper_text
    assert "MINI_SWE_AGENT_PYTHON" in wrapper_text
    assert "/opt/mini-swe-agent/bin/python" in wrapper_text
    assert "MINI_SWE_AGENT_CONFIG_PATH" in wrapper_text
    assert "contextlib.redirect_stdout(sys.stderr)" in wrapper_text
    assert "from minisweagent.config import builtin_config_dir" in wrapper_text
    assert "MINI_RUNTIME_CONFIG_PATH" in wrapper_text
    assert "yaml.safe_load" in wrapper_text
    assert 'config.setdefault("agent", {})["step_limit"] = step_limit' in wrapper_text
    assert "mini_runtime.yaml" in wrapper_text
    assert '-c "${MINI_RUNTIME_CONFIG_PATH}"' in wrapper_text
    assert '"agent.step_limit=${STEP_LIMIT}"' not in wrapper_text
    assert '-l "${COST_LIMIT}"' in wrapper_text
    assert '-o "${TRAJECTORY_PATH}"' in wrapper_text
    assert "mini_swe_agent_stdout.log" in wrapper_text
    assert "mini_swe_agent_stderr.log" in wrapper_text
    assert "mini_swe_agent_settings.env" in wrapper_text
    assert "cost_tracking=${COST_TRACKING}" in wrapper_text
    assert "tool_choice=${TOOL_CHOICE}" in wrapper_text
    assert 'config.setdefault("model", {}).setdefault("model_kwargs", {})["tool_choice"] = tool_choice' in wrapper_text
    assert ': >|"${OUTPUT_DIR}/mini_swe_agent_stdout.log"' in wrapper_text
    assert ': >|"${OUTPUT_DIR}/mini_swe_agent_stderr.log"' in wrapper_text
    assert '} >|"${OUTPUT_DIR}/mini_swe_agent_settings.env"' in wrapper_text
    assert "set +x" in wrapper_text
    assert "-y" in wrapper_text


def test_mini_swe_agent_image_keeps_kubernetes_clone_cacheable_when_wrapper_changes() -> None:
    dockerfile_text = (REPO_ROOT / "docker" / "Dockerfile.mini_swe_agent").read_text()

    assert dockerfile_text.index("RUN git clone") < dockerfile_text.index(
        "COPY docker/run_mini_swe_agent.sh",
    )


def test_local_llm_proxy_image_serves_the_proxy_script_with_project_dependency() -> None:
    dockerfile_text = (REPO_ROOT / "docker" / "Dockerfile.local_llm_proxy").read_text()
    dockerignore_text = (REPO_ROOT / ".dockerignore").read_text()

    assert "httpx==0.28.1" in dockerfile_text
    assert "COPY src/local_llm_proxy.py" in dockerfile_text
    assert 'ENTRYPOINT ["python", "/app/local_llm_proxy.py"]' in dockerfile_text
    assert "!src/" in dockerignore_text
    assert "!src/local_llm_proxy.py" in dockerignore_text


def test_local_llm_compose_keeps_agent_network_internal_and_exposes_only_proxy_to_host() -> None:
    compose_text = (REPO_ROOT / "docker-compose.local-llm.yml").read_text()

    assert "name: k8s-bench-local" in compose_text
    assert "internal: true" in compose_text
    assert "container_name: k8s-bench-llm" in compose_text
    assert "container_name: k8s-bench-proxy" in compose_text
    assert "http://k8s-bench-llm:8001/v1" in compose_text
    assert "127.0.0.1:8002:8002" in compose_text
    assert "--tool-call-parser" in compose_text
    assert "qwen3_coder" in compose_text


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _iter_docker_configs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    if "agent_matrix" in spec:
        return [spec["agent_matrix"]["docker"]]
    return [agent_config["docker"] for agent_config in spec.get("agent_configs", [])]


def _first_shell_token(command: str) -> str:
    return shlex.split(command)[0]


def _dockerfile_mentions_command(dockerfile_text: str, command: str) -> bool:
    return f"/usr/local/bin/{command}" in dockerfile_text or f" {command}" in dockerfile_text
