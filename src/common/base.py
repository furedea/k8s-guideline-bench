"""Shared Pydantic base models."""

import pydantic


class FrozenModel(pydantic.BaseModel):
    """Strict immutable base model for project value objects."""

    model_config = pydantic.ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )
