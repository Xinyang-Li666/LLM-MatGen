from __future__ import annotations

import builtins

import pytest

from llm_matgen.trajectories.representative.config import SOAPConfig


def test_soap_config_validates_and_normalizes_groups():
    config = SOAPConfig.from_dict({"r_cut": 4.5, "n_max": 4, "l_max": 3, "groups": {"TM": [22, 40], "B": [5]}})
    assert config.r_cut == 4.5 and config.groups["TM"] == (22, 40)
    with pytest.raises(ValueError):
        SOAPConfig.from_dict({"compression": "bad"})
    with pytest.raises(ValueError):
        SOAPConfig.from_dict({"groups": {"TM": [22], "B": [22]}})
    with pytest.raises(ValueError):
        SOAPConfig.from_dict({"pooling": "bad"})


def test_dscribe_import_is_lazy_and_has_install_hint(monkeypatch):
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("dscribe"):
            raise ImportError("blocked")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    from llm_matgen.trajectories.representative.soap import SOAPDescriptorBackend

    with pytest.raises(RuntimeError, match=r"llm-matgen\[soap\]"):
        SOAPDescriptorBackend((5,), SOAPConfig())
