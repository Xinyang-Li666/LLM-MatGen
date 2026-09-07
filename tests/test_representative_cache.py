from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from llm_matgen.trajectories.representative.cache import (
    CacheFingerprint,
    DescriptorCache,
    fingerprint_payload,
)


def test_fingerprint_is_canonical_and_changes_with_input(tmp_path: Path):
    payload = {
        "source": str(tmp_path / "中文" / "traj.extxyz"),
        "file_sha256": "abc",
        "mapping": {"1": "Ti"},
        "descriptor": {"bin": 0.05, "r_max": 6.0},
    }
    first = fingerprint_payload(payload)
    second = fingerprint_payload({**payload, "descriptor": {"bin": 0.1, "r_max": 6.0}})
    assert first.digest != second.digest
    assert json.loads(first.payload_json)["source"].endswith("traj.extxyz")
    assert len(first.digest) == 64


def test_cache_memmap_and_completed_chunks(tmp_path: Path):
    cache = DescriptorCache(tmp_path / "缓存")
    fingerprint = CacheFingerprint.from_payload({"input": "x", "value": 1.25})
    cache.initialize(fingerprint)
    array = cache.create_memmap("rdf", (5, 3))
    array[0:2] = 1.0
    array.flush()
    cache.mark_chunk_complete("rdf", 0, 2)
    assert cache.completed_chunks("rdf") == ((0, 2),)
    assert np.asarray(cache.open_memmap("rdf", (5, 3)))[0, 0] == 1.0


def test_cache_rejects_overlap_and_invalid_fingerprint(tmp_path: Path):
    cache = DescriptorCache(tmp_path / "cache")
    fingerprint = CacheFingerprint.from_payload({"x": 1})
    cache.initialize(fingerprint)
    cache.mark_chunk_complete("rdf", 0, 2)
    with pytest.raises(ValueError, match="overlap"):
        cache.mark_chunk_complete("rdf", 1, 3)
    with pytest.raises(ValueError, match="fingerprint"):
        cache.validate(CacheFingerprint.from_payload({"x": 2}))


def test_partial_chunk_is_not_complete_and_recompute_uses_new_state(tmp_path: Path):
    cache = DescriptorCache(tmp_path / "cache")
    fp = CacheFingerprint.from_payload({"x": 1})
    cache.initialize(fp)
    cache.create_memmap("rdf", (4, 2))
    part = cache.root / "rdf.0-2.part"
    part.write_text("incomplete", encoding="utf-8")
    assert cache.completed_chunks("rdf") == ()
    recomputed = cache.recompute(fp)
    assert recomputed.digest != fp.digest
