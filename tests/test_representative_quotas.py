import pytest

from llm_matgen.trajectories.representative.quotas import allocate_proportional_quotas


def test_proportional_quotas_match_tmb2_baseline_counts():
    counts = {"ALL_T": 31823, "DPA-4": 42542, "MatterSim": 6610}

    assert allocate_proportional_quotas(counts, 20000) == {
        "ALL_T": 7860,
        "DPA-4": 10507,
        "MatterSim": 1633,
    }
    assert allocate_proportional_quotas(counts, 5000) == {
        "ALL_T": 1965,
        "DPA-4": 2627,
        "MatterSim": 408,
    }


def test_proportional_quotas_handle_caps_and_small_budgets():
    assert allocate_proportional_quotas({"A": 1, "B": 9}, 5) == {"A": 1, "B": 4}
    with pytest.raises(ValueError, match="smaller"):
        allocate_proportional_quotas({"A": 1, "B": 1}, 1)
    assert allocate_proportional_quotas({"A": 0, "B": 2}, 10) == {"B": 2}
    assert allocate_proportional_quotas({}, 4) == {}


def test_proportional_quotas_reject_invalid_target():
    with pytest.raises(ValueError, match="positive"):
        allocate_proportional_quotas({"A": 1}, 0)
