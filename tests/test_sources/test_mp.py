import pytest
from types import SimpleNamespace


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


class FakeSummaryEndpoint:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.documents)


def test_mp_search_maps_filters_sorts_and_enforces_limit():
    from llm_matgen.sources.mp import MPCollector, MaterialSearchQuery

    endpoint = FakeSummaryEndpoint(
        [
            {"material_id": "mp-20", "formula_pretty": "Li2O", "band_gap": 2.0},
            {"material_id": "mp-3", "formula_pretty": "LiCoO2", "band_gap": 1.0},
            {"material_id": "mp-10", "formula_pretty": "Li2O2", "band_gap": 3.0},
        ]
    )
    client = SimpleNamespace(materials=SimpleNamespace(summary=endpoint))
    collector = MPCollector(api_key="key", client_factory=lambda key: client)
    result = collector.search(
        MaterialSearchQuery(
            elements=["Li", "O"],
            chemsys="Li-O",
            band_gap_min=0.5,
            band_gap_max=4.0,
            formation_energy_max=-0.1,
            limit=2,
        )
    )
    assert [item.material_id for item in result] == ["mp-10", "mp-20"]
    call = endpoint.calls[0]
    assert call["elements"] == ["Li", "O"]
    assert call["chemsys"] == "Li-O"
    assert call["band_gap"] == (0.5, 4.0)
    assert call["formation_energy"] == (None, -0.1)


def test_mp_search_supports_formula_and_material_ids():
    from llm_matgen.sources.mp import MPCollector, MaterialSearchQuery

    endpoint = FakeSummaryEndpoint([{"material_id": "mp-1", "formula_pretty": "Si"}])
    client = SimpleNamespace(materials=SimpleNamespace(summary=endpoint))
    collector = MPCollector(api_key="key", client_factory=lambda key: client)
    collector.search(MaterialSearchQuery(formula="Si", material_ids=["mp-1"], n_elements=1))
    assert endpoint.calls[0]["formula"] == "Si"
    assert endpoint.calls[0]["material_ids"] == ["mp-1"]
    assert endpoint.calls[0]["num_elements"] == 1


def test_mp_search_query_rejects_empty_conflicting_and_system_limit():
    from pydantic import ValidationError
    from llm_matgen.sources.mp import MPCollector, MPDataError, MaterialSearchQuery

    with pytest.raises(ValidationError, match="search criterion"):
        MaterialSearchQuery()
    with pytest.raises(ValidationError, match="band gap"):
        MaterialSearchQuery(formula="Si", band_gap_min=2, band_gap_max=1)
    collector = MPCollector(api_key="key", client_factory=lambda key: FakeClient())
    with pytest.raises(MPDataError, match="system limit"):
        collector.search(MaterialSearchQuery(formula="Si", limit=1001))
