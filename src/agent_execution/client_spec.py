"""Completion client specification for configuration-driven client selection."""

import enum

import base
import pydantic


class ClientType(enum.StrEnum):
    """Transport dialect for a completion provider."""

    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


class ClientSpec(base.FrozenModel):
    """Configuration describing how to instantiate a completion client."""

    client_type: ClientType
    api_key_env: str
    base_url: str | None = None

    @pydantic.field_validator("client_type", mode="before")
    @classmethod
    def validate_client_type(cls, value: object) -> object:
        if isinstance(value, str):
            return ClientType(value)
        return value
