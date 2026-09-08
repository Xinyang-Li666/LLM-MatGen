"""Release-time checks that never echo suspected secret values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?:MP_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|
        AWS_SECRET_ACCESS_KEY|API_KEY|TOKEN|SECRET|PASSWORD)\b
    [^\S\r\n]*[:=][^\S\r\n]*["']?([^\s"'#;,]+)
    """
)
_KNOWN_SECRET = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16})(?![A-Za-z0-9])"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_WINDOWS_USER_PATH = re.compile(r"(?i)\b[A-Z]:\\Users\\([^\\/\s]+)(?:\\|/)")
_UNIX_USER_PATH = re.compile(r"/(?:Users|home)/([^/\s]+)(?:/|$)")
_WINDOWS_ESCAPED_PATH = re.compile(r'''["'][A-Z]:(?:\\{2})+''')
_SSH_WRAPPER = re.compile(r"(?im)^\s*(?:proxycommand|remotecommand)\s+|\bssh\s+[^\r\n]*(?:-file|-wrapper)\b")


@dataclass(frozen=True)
class Finding:
    path: Path
    rule: str


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized.startswith(
            (
                "your-",
                "example",
                "dummy",
                "test-",
                "replace-",
                "changeme",
                "<",
                "{",
                "${",
                "$env:",
            )
        )
        or set(normalized) <= {"x", "*", "-"}
    )


def _is_placeholder_username(username: str) -> bool:
    normalized = username.lower()
    return (
        normalized in {"user", "username", "name", "<user>", "<username>"}
        or normalized.startswith(("%", "$", "{", "<"))
    )


def scan_text(path: Path, text: str) -> list[Finding]:
    """Return rule/path findings without retaining matched content."""
    rules: set[str] = set()

    if any(
        len(match.group(1).strip("\"'")) >= 16
        and not _is_placeholder(match.group(1))
        for match in _SECRET_ASSIGNMENT.finditer(text)
    ):
        rules.add("non-placeholder-secret")
    if _KNOWN_SECRET.search(text) or _PRIVATE_KEY.search(text):
        rules.add("known-secret-pattern")

    windows_users = (match.group(1) for match in _WINDOWS_USER_PATH.finditer(text))
    unix_users = (match.group(1) for match in _UNIX_USER_PATH.finditer(text))
    if any(not _is_placeholder_username(user) for user in (*windows_users, *unix_users)):
        rules.add("personal-absolute-path")
    if _WINDOWS_ESCAPED_PATH.search(text):
        rules.add("personal-absolute-path")
    if _SSH_WRAPPER.search(text):
        rules.add("ssh-wrapper")

    return [Finding(path=path, rule=rule) for rule in sorted(rules)]


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        Path(raw.decode("utf-8"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def scan_repository(root: Path) -> list[Finding]:
    """Scan Git-tracked UTF-8 text files in their current working-tree state."""
    findings: list[Finding] = []
    for relative_path in _tracked_files(root):
        path = root / relative_path
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(relative_path, text))
    return findings


def format_findings(findings: list[Finding]) -> str:
    """Format only file paths and rule names, never matching source text."""
    return "\n".join(f"{finding.path.as_posix()}: {finding.rule}" for finding in findings)
