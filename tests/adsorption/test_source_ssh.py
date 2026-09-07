import base64
import json
from pathlib import Path

import pytest


class _Completed:
    def __init__(self, stdout: str, *, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_ssh_source_uses_fixed_program_argument_list_and_stable_batch_order(tmp_path: Path):
    from llm_matgen.adsorption.config import SSHSourceConfig
    from llm_matgen.adsorption.sources.ssh import SSHCaseSource

    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        payload = json.dumps(
            {
                "jobs": [
                    {"job_id": "z", "files": []},
                    {"job_id": "a", "files": []},
                ]
            }
        )
        return _Completed(payload)

    source = SSHCaseSource(
        SSHSourceConfig(name="remote", host="example.org", user="alice", root="/cases", port=2222),
        runner=runner,
        timeout=17,
    )
    jobs = source.discover()

    assert [job.job_id for job in jobs] == ["a", "z"]
    argv, kwargs = calls[0]
    assert argv[:4] == ["ssh", "-p", "2222", "alice@example.org"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 17
    assert "-c" in argv
    encoded = next(item for item in argv if item.startswith("ey"))
    assert json.loads(base64.b64decode(encoded).decode()) == {"operation": "discover", "root": "/cases"}


@pytest.mark.parametrize("job_id", ["../case", "/etc", "bad\x00path", "a\\b"])
def test_ssh_source_rejects_unsafe_job_paths(job_id):
    from llm_matgen.adsorption.config import SSHSourceConfig
    from llm_matgen.adsorption.sources.base import CaseSourceError
    from llm_matgen.adsorption.sources.ssh import SSHCaseSource

    source = SSHCaseSource(SSHSourceConfig(name="remote", host="example.org", root="/cases"), runner=lambda *_args, **_kwargs: None)
    with pytest.raises(CaseSourceError):
        source.snapshot(job_id)


def test_ssh_source_reports_truncated_remote_errors():
    from llm_matgen.adsorption.config import SSHSourceConfig
    from llm_matgen.adsorption.sources.base import CaseSourceError
    from llm_matgen.adsorption.sources.ssh import SSHCaseSource

    def runner(_argv, **_kwargs):
        return _Completed("", returncode=7, stderr="x" * 1000)

    source = SSHCaseSource(SSHSourceConfig(name="remote", host="example.org", root="/cases"), runner=runner, error_limit=80)
    with pytest.raises(CaseSourceError, match="x{20}") as exc_info:
        source.discover()
    assert len(str(exc_info.value)) < 200


def test_ssh_source_rejects_invalid_json_and_does_not_use_shell():
    from llm_matgen.adsorption.config import SSHSourceConfig
    from llm_matgen.adsorption.sources.base import CaseSourceError
    from llm_matgen.adsorption.sources.ssh import SSHCaseSource

    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Completed("not-json")

    source = SSHCaseSource(SSHSourceConfig(name="remote", host="example.org", root="/cases"), runner=runner)
    with pytest.raises(CaseSourceError, match="invalid JSON"):
        source.discover()
    assert calls[0][1]["shell"] is False
