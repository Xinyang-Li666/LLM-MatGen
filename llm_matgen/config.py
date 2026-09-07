"""Atomic storage for non-sensitive user configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .adsorption.config import AdsorptionConfig

try:
    from platformdirs import user_config_dir
except ImportError:  # pragma: no cover - dependency is declared for installations
    user_config_dir = None


class ConfigError(ValueError):
    pass


def _is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("key", "token", "secret", "password"))


def _find_sensitive(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for name, item in value.items():
            current = f"{path}.{name}" if path else str(name)
            if _is_sensitive(str(name)):
                return current
            found = _find_sensitive(item, current)
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_sensitive(item, f"{path}[{index}]")
            if found:
                return found
    return None


def redact(value: Any, key: str = "") -> Any:
    if key and _is_sensitive(key):
        return "***REDACTED***"
    if isinstance(value, dict):
        return {name: redact(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class ConfigManager:
    ALLOWED_FIELDS = {"provider", "model", "adsorption"}

    def __init__(self, path: Path | None = None):
        configured = os.environ.get("LLM_MATGEN_CONFIG")
        default_dir = user_config_dir("llm-matgen") if user_config_dir else str(Path.home() / ".config" / "llm-matgen")
        self.path = Path(path or configured or (Path(default_dir) / "config.json"))

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"failed to read configuration: {self.path}") from exc
        if not isinstance(data, dict):
            raise ConfigError("configuration root must be an object")
        sensitive_path = _find_sensitive(data)
        if sensitive_path:
            raise ConfigError(f"sensitive fields are not allowed in the configuration file: {sensitive_path}")
        return data

    def set(self, field: str, value: str) -> dict[str, Any]:
        if field not in self.ALLOWED_FIELDS:
            raise ConfigError(f"unsupported configuration field: {field}")
        if not value.strip():
            raise ConfigError(f"configuration field {field} cannot be empty")
        data = self.load()
        data[field] = value.strip()
        self._write_atomic(data)
        return data

    def load_adsorption(self) -> AdsorptionConfig:
        return AdsorptionConfig.model_validate(self.load().get("adsorption", {}))

    def set_adsorption(self, value: AdsorptionConfig) -> dict[str, Any]:
        data = self.load()
        data["adsorption"] = value.model_dump(mode="json")
        self._write_atomic(data)
        return data

    def show(self) -> dict[str, Any]:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.startswith("LLM_MATGEN_") or _is_sensitive(name)
        }
        return {
            "config_path": str(self.path),
            "config": redact(self.load()),
            "environment": redact(environment),
        }

    def _write_atomic(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
