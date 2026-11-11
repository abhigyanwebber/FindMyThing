from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    """Unknown request fields are rejected (contract §1)."""

    model_config = ConfigDict(extra="forbid")
