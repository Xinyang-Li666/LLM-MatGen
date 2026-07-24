import pytest


class FakeHTTPError(RuntimeError):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class FakeClient:
    def __init__(self, outcome="ok"):
        self.outcome = outcome

    def ping(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_mp_collector_injects_factory_and_reads_explicit_or_environment_key(monkeypatch):
    from llm_matgen.sources.mp import MPCollector

    captured = []

    def factory(api_key):
        captured.append(api_key)
        return FakeClient()

    monkeypatch.setenv("MP_API_KEY", "environment-key")
    assert MPCollector(client_factory=factory).execute(lambda client: client.ping()) == "ok"
    assert MPCollector(api_key="explicit-key", client_factory=factory).execute(lambda client: client.ping()) == "ok"
    assert captured == ["environment-key", "explicit-key"]


def test_mp_collector_requires_key(monkeypatch):
    from llm_matgen.sources.mp import MPAuthenticationError, MPCollector

    monkeypatch.delenv("MP_API_KEY", raising=False)
    with pytest.raises(MPAuthenticationError, match="MP_API_KEY"):
        MPCollector(client_factory=lambda key: FakeClient())


@pytest.mark.parametrize(
    "error,expected_type",
    [
        (FakeHTTPError(401), "MPAuthenticationError"),
        (FakeHTTPError(403), "MPAuthenticationError"),
        (FakeHTTPError(429), "MPRateLimitError"),
        (FakeHTTPError(503), "MPUnavailableError"),
        (TimeoutError("timeout"), "MPUnavailableError"),
        (ValueError("malformed"), "MPDataError"),
    ],
)
def test_mp_collector_maps_boundary_errors(error, expected_type):
    from llm_matgen.sources import mp

    collector = mp.MPCollector(api_key="key", client_factory=lambda key: FakeClient(error))
    with pytest.raises(getattr(mp, expected_type)):
        collector.execute(lambda client: client.ping())
