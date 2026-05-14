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
    assert "MSWEA_CONFIGURED=1 mini" in wrapper_text
    assert "--agent-class default" in wrapper_text
    assert "--exit-immediately" in wrapper_text
    assert "MINI_SWE_AGENT_STEP_LIMIT" in wrapper_text
    assert "agent.step_limit=${STEP_LIMIT}" in wrapper_text
    assert '-o "${TRAJECTORY_PATH}"' in wrapper_text
    assert "mini_swe_agent_stdout.log" in wrapper_text
    assert "mini_swe_agent_stderr.log" in wrapper_text
    assert "mini_swe_agent_settings.env" in wrapper_text
    assert "set +x" in wrapper_text
    assert "-y" in wrapper_text


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
