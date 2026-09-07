"""Bounded, read-only SSH case source using a fixed remote helper."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import SSHSourceConfig
from .base import CaseSourceError, JobSnapshot, RemoteFileSnapshot


REMOTE_PROGRAM = (
    "import base64,json,sys; "
    "request=json.loads(base64.b64decode(sys.argv[1])); "
    "print(json.dumps({'operation': request['operation'], 'root': request['root']}))"
)


class SSHCaseSource:
    def __init__(
        self,
        config: SSHSourceConfig,
        *,
        runner: Callable[..., Any] | None = None,
        timeout: float = 30.0,
        error_limit: int = 512,
    ):
        if timeout <= 0 or error_limit <= 0:
            raise ValueError("timeout and error_limit must be positive")
        self.config = config
        self.runner = runner or self._default_runner
        self.timeout = timeout
        self.error_limit = error_limit

    @staticmethod
    def _default_runner(argv, **kwargs):
        import subprocess

        return subprocess.run(argv, **kwargs)

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        if not isinstance(job_id, str) or not job_id or "\x00" in job_id:
            raise CaseSourceError("job path cannot be empty or contain NUL")
        if job_id.startswith(("/", "\\")) or "\\" in job_id:
            raise CaseSourceError(f"job path is not relative: {job_id}")
        if any(part == ".." for part in job_id.split("/")):
            raise CaseSourceError(f"job path escapes source root: {job_id}")
        return job_id

    def _command(self, operation: str, job_id: str | None = None) -> list[str]:
        payload = {"operation": operation, "root": self.config.root}
        if job_id is not None:
            payload["job_id"] = self._validate_job_id(job_id)
        encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        target = f"{self.config.user}@{self.config.host}" if self.config.user else self.config.host
        command = ["ssh", "-p", str(self.config.port)]
        if self.config.identity_file is not None:
            command.extend(["-i", str(self.config.identity_file)])
        command.extend([target, "python3", "-c", REMOTE_PROGRAM, encoded])
        return command

    def _invoke(self, operation: str, job_id: str | None = None) -> Any:
        argv = self._command(operation, job_id)
        try:
            result = self.runner(
                argv,
                shell=False,
                timeout=self.timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            raise CaseSourceError(f"SSH case source failed: {exc}") from exc
        if getattr(result, "returncode", 1) != 0:
            message = str(getattr(result, "stderr", ""))[: self.error_limit]
            raise CaseSourceError(f"SSH case source returned {result.returncode}: {message}")
        try:
            return json.loads(getattr(result, "stdout", ""))
        except (TypeError, json.JSONDecodeError) as exc:
            raise CaseSourceError("SSH case source returned invalid JSON") from exc

    @staticmethod
    def _job(value: Any) -> JobSnapshot:
        if not isinstance(value, dict) or not isinstance(value.get("job_id"), str):
            raise CaseSourceError("SSH case source returned an invalid job")
        files = []
        for item in value.get("files", []):
            if not isinstance(item, dict):
                raise CaseSourceError("SSH case source returned an invalid file")
            try:
                files.append(RemoteFileSnapshot(**item))
            except TypeError as exc:
                raise CaseSourceError("SSH case source returned an invalid file") from exc
        files.sort(key=lambda item: item.relative_path)
        return JobSnapshot(job_id=value["job_id"], source="ssh", files=tuple(files))

    def discover(self) -> tuple[JobSnapshot, ...]:
        payload = self._invoke("discover")
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise CaseSourceError("SSH case source returned an invalid discovery response")
        return tuple(sorted((self._job(item) for item in payload["jobs"]), key=lambda item: item.job_id))

    def snapshot(self, job_id: str) -> JobSnapshot:
        payload = self._invoke("snapshot", self._validate_job_id(job_id))
        value = payload.get("job") if isinstance(payload, dict) and "job" in payload else payload
        return self._job(value)
