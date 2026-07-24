"""Models for non-blocking lightweight structure checks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from llm_matgen.generators.models import CheckLevel, JsonValue


class CheckIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    level: CheckLevel
    message: str
    site_ids: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class CheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_atoms: int
    formula: str
    issues: list[CheckIssue] = Field(default_factory=list)
    metrics: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def can_export(self) -> bool:
        return not any(issue.level is CheckLevel.ERROR for issue in self.issues)
