"""Typed, credential-free configuration for adsorption case sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

try:
    from platformdirs import user_data_dir, user_config_dir
except ImportError:  # pragma: no cover - dependency is declared for installations
    def user_config_dir(appname: str) -> str:
        return str(Path.home() / ".config" / appname)

    def user_data_dir(appname: str) -> str:
        return str(Path.home() / ".local" / "share" / appname)


def _safe_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError(f"{field_name} must be non-empty and contain no control characters")
    return value


class _SourceBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str

    _validate_name = field_validator("name")(
        lambda value: _safe_text(value, "source name")
    )


class LocalSourceConfig(_SourceBase):
    type: Literal["local"] = "local"
    root: Path


class SSHSourceConfig(_SourceBase):
    type: Literal["ssh"] = "ssh"
    host: str
    root: str
    user: str | None = None
    port: PositiveInt = 22
    identity_file: Path | None = None

    _validate_host = field_validator("host")(
        lambda value: _safe_text(value, "host")
    )
    _validate_root = field_validator("root")(
        lambda value: _safe_text(value, "root")
    )
    _validate_user = field_validator("user")(
        lambda value: _safe_text(value, "user") if value is not None else value
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if value > 65535:
            raise ValueError("port must be between 1 and 65535")
        return value


SourceConfig = Annotated[
    LocalSourceConfig | SSHSourceConfig,
    Field(discriminator="type"),
]


class AdsorptionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sources: tuple[SourceConfig, ...] = ()
    store_root: Path | None = None

    @property
    def resolved_store_root(self) -> Path:
        return self.store_root or Path(user_data_dir("llm-matgen")) / "adsorption"

