import pytest
from types import SimpleNamespace
from pathlib import Path
from pymatgen.core import Lattice, Structure


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


def test_mp_search_postfilters_structure_class_and_records_evidence():
    from llm_matgen.sources.classifier import ClassificationResult
    from llm_matgen.sources.mp import MPCollector, MaterialSearchQuery

    class FakeClassifier:
        def classify(self, structure, target=None):
            matched = structure == "layered-structure"
            return ClassificationResult(
                label="layered" if matched else "unknown",
                matched=matched,
                score=1 if matched else 0,
                method="fake-geometry",
                evidence={"target": target},
            )

    endpoint = FakeSummaryEndpoint(
        [
            {"material_id": "mp-1", "structure": "layered-structure"},
            {"material_id": "mp-2", "structure": "bulk-structure"},
        ]
    )
    client = SimpleNamespace(materials=SimpleNamespace(summary=endpoint))
    result = MPCollector(
        api_key="key", client_factory=lambda key: client, classifier=FakeClassifier()
    ).search(MaterialSearchQuery(elements=["C"], structure_class="layered"))
    assert [item.material_id for item in result] == ["mp-1"]
    assert result[0].classification.evidence["target"] == "layered"


class DownloadEndpoint:
    def __init__(self, documents, failing=()):
        self.documents = documents
        self.failing = set(failing)
        self.calls = []

    def search(self, **kwargs):
        material_id = kwargs["material_ids"][0]
        self.calls.append(material_id)
        if material_id in self.failing:
            raise RuntimeError("failed download")
        return [self.documents[material_id]]


def mp_structure(element="Si"):
    return Structure(Lattice.cubic(5.4), [element], [[0, 0, 0]])


def test_mp_download_writes_atomic_structure_metadata_and_reuses_matching_file(tmp_path: Path):
    from llm_matgen.sources.mp import MPCollector

    endpoint = DownloadEndpoint(
        {"mp-1": {"material_id": "mp-1", "structure": mp_structure(), "database_version": "2026.07"}}
    )
    client = SimpleNamespace(materials=SimpleNamespace(summary=endpoint))
    collector = MPCollector(api_key="key", client_factory=lambda key: client)
    first = collector.download(["mp-1"], tmp_path)
    second = collector.download(["mp-1"], tmp_path)
    assert not first.failures
    assert first.successes[0].database_version == "2026.07"
    assert first.successes[0].local_path.exists()
    assert first.successes[0].local_path.with_suffix(".json").exists()
    assert second.successes[0].local_path == first.successes[0].local_path
    assert endpoint.calls == ["mp-1"]


def test_mp_download_uses_new_version_path_when_existing_metadata_mismatches(tmp_path: Path):
    from llm_matgen.sources.mp import MPCollector

    endpoint = DownloadEndpoint(
        {"mp-1": {"material_id": "mp-1", "structure": mp_structure(), "database_version": "v1"}}
    )
    client = SimpleNamespace(materials=SimpleNamespace(summary=endpoint))
    collector = MPCollector(api_key="key", client_factory=lambda key: client)
    existing = tmp_path / "mp-1.cif"
    existing.write_text("unrelated", encoding="utf-8")
    existing.with_suffix(".json").write_text('{"structure_hash":"wrong"}', encoding="utf-8")
    result = collector.download(["mp-1"], tmp_path)
    assert result.successes[0].local_path.name == "mp-1-v2.cif"
    assert existing.read_text(encoding="utf-8") == "unrelated"


def test_mp_download_preserves_partial_successes(tmp_path: Path):
    from llm_matgen.sources.mp import MPCollector

    endpoint = DownloadEndpoint(
        {"mp-1": {"material_id": "mp-1", "structure": mp_structure(), "database_version": "v1"}},
        failing={"mp-2"},
    )
    client = SimpleNamespace(materials=SimpleNamespace(summary=endpoint))
    result = MPCollector(api_key="key", client_factory=lambda key: client).download(
        ["mp-1", "mp-2"], tmp_path
    )
    assert [item.source_reference for item in result.successes] == ["mp-1"]
    assert [item.material_id for item in result.failures] == ["mp-2"]
    assert result.successes[0].local_path.exists()


class PropertyEndpoint:
    def __init__(self, name, documents):
        self.name = name
        self.documents = documents
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.documents


def test_mp_fetch_properties_tracks_endpoint_method_and_unavailable_values():
    from llm_matgen.sources.mp import MPCollector

    names = ["thermo", "electronic", "magnetism", "dielectric", "phonon", "elasticity"]
    endpoints = {
        name: PropertyEndpoint(
            name,
            [] if name == "phonon" else [{"material_id": "mp-1", "value": name, "method": "DFT"}],
        )
        for name in names
    }
    materials = SimpleNamespace(
        thermo=endpoints["thermo"],
        electronic_structure=endpoints["electronic"],
        magnetism=endpoints["magnetism"],
        dielectric=endpoints["dielectric"],
        phonon=endpoints["phonon"],
        elasticity=endpoints["elasticity"],
    )
    collector = MPCollector(
        api_key="key", client_factory=lambda key: SimpleNamespace(materials=materials)
    )
    result = collector.fetch_properties(["mp-1"], names)[0]
    assert result.properties["thermo"].endpoint == "materials.thermo"
    assert result.properties["thermo"].method == "DFT"
    assert result.properties["phonon"].available is False
    assert result.properties["phonon"].value is None


def test_mp_special_reference_queries_use_dedicated_endpoints():
    from llm_matgen.sources.mp import MPCollector

    substrates = PropertyEndpoint("substrates", [{"material_id": "mp-1", "substrate_id": "mp-2"}])
    grain_boundaries = PropertyEndpoint("grain_boundaries", [{"material_id": "mp-1", "sigma": 5}])
    materials = SimpleNamespace(substrates=substrates, grain_boundaries=grain_boundaries)
    collector = MPCollector(
        api_key="key", client_factory=lambda key: SimpleNamespace(materials=materials)
    )
    assert collector.search_substrates(["mp-1"])[0]["substrate_id"] == "mp-2"
    assert collector.search_grain_boundaries(["mp-1"])[0]["sigma"] == 5
    assert substrates.calls[0]["material_ids"] == ["mp-1"]
    assert grain_boundaries.calls[0]["material_ids"] == ["mp-1"]


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FlakyClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def ping(self):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_mp_retry_uses_exponential_backoff_for_server_errors():
    from llm_matgen.sources.mp import MPCollector

    clock = FakeClock()
    client = FlakyClient([FakeHTTPError(503), FakeHTTPError(503), "ok"])
    collector = MPCollector(
        api_key="key", client_factory=lambda key: client,
        max_attempts=3, base_delay=0.5, jitter=0,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )
    assert collector.execute(lambda active: active.ping()) == "ok"
    assert clock.sleeps == [0.5, 1.0]


def test_mp_retry_respects_retry_after_and_does_not_retry_4xx():
    from llm_matgen.sources.mp import MPCollector, MPDataError

    rate_error = FakeHTTPError(429)
    rate_error.headers = {"Retry-After": "2"}
    clock = FakeClock()
    rate_client = FlakyClient([rate_error, "ok"])
    collector = MPCollector(
        api_key="key", client_factory=lambda key: rate_client,
        max_attempts=2, jitter=0, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    assert collector.execute(lambda active: active.ping()) == "ok"
    assert clock.sleeps == [2.0]

    bad_client = FlakyClient([FakeHTTPError(400), "should-not-run"])
    with pytest.raises(MPDataError):
        MPCollector(
            api_key="key", client_factory=lambda key: bad_client,
            max_attempts=3, sleep=clock.sleep, monotonic=clock.monotonic,
        ).execute(lambda active: active.ping())
    assert bad_client.calls == 1


def test_mp_retry_cancellation_and_exhaustion_preserve_original_cause():
    from llm_matgen.sources.mp import MPCancelledError, MPCollector, MPUnavailableError

    with pytest.raises(MPCancelledError):
        MPCollector(
            api_key="key", client_factory=lambda key: FakeClient(), cancel_check=lambda: True
        ).execute(lambda active: active.ping())

    original = FakeHTTPError(503)
    clock = FakeClock()
    with pytest.raises(MPUnavailableError) as caught:
        MPCollector(
            api_key="key", client_factory=lambda key: FlakyClient([original]),
            max_attempts=1, sleep=clock.sleep, monotonic=clock.monotonic,
        ).execute(lambda active: active.ping())
    assert caught.value.__cause__ is original
