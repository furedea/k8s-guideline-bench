"""Tests for ClientSpec / ClientType value objects."""

import client_spec
import pytest


def test_client_spec_accepts_serialized_client_type_string() -> None:
    spec = client_spec.ClientSpec(
        client_type="openai_compatible",  # ty: ignore[invalid-argument-type]
        api_key_env="OPENCODE_API_KEY",
        base_url="https://opencode.ai/zen/go/v1",
    )

    assert spec.client_type == client_spec.ClientType.OPENAI_COMPATIBLE
    assert spec.base_url == "https://opencode.ai/zen/go/v1"


def test_client_spec_defaults_base_url_to_none() -> None:
    spec = client_spec.ClientSpec(
        client_type=client_spec.ClientType.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
    )

    assert spec.base_url is None


def test_client_spec_rejects_unknown_client_type_string() -> None:
    with pytest.raises(ValueError, match="nonexistent"):
        _ = client_spec.ClientSpec(
            client_type="nonexistent",  # ty: ignore[invalid-argument-type]
            api_key_env="KEY",
        )
