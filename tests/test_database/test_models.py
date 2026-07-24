from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError


def make_snapshot(**updates):
    from llm_matgen.database.models import MaterialSnapshot

    values = dict(
        snapshot_id=uuid4(), material_id="mp-1", source_db_version="v1",
        structure_hash="abc", formula="LiCoO2", elements=["O", "Li", "Co", "O"],
        n_elements=3, properties={"band_gap": 1.2, "formation_energy": -2.0},
        property_origins={"band_gap": "materials.electronic_structure"},
        raw_json={"source": "fake"}, fetched_at=datetime.now(timezone.utc),
    )
    values.update(updates)
    return MaterialSnapshot(**values)


def test_material_snapshot_normalizes_elements_and_utc_time():
    snapshot = make_snapshot()
    assert snapshot.elements == ["Co", "Li", "O"]
    assert snapshot.fetched_at.tzinfo is not None
    assert snapshot.fetched_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_material_snapshot_rejects_non_finite_properties(value):
    with pytest.raises(ValidationError, match="finite"):
        make_snapshot(properties={"band_gap": value})


def test_local_query_rejects_inverted_ranges():
    from llm_matgen.database.models import LocalMaterialQuery

    with pytest.raises(ValidationError, match="band gap"):
        LocalMaterialQuery(band_gap_min=2, band_gap_max=1)
