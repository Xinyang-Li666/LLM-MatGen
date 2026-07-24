import json
from pathlib import Path
from types import SimpleNamespace


class FakeCollector:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query):
        return [SimpleNamespace(
            material_id="mp-1", formula_pretty="Si", band_gap=1.1,
            formation_energy_per_atom=-0.5, classification=None,
        )]

    def download(self, material_ids, output_dir):
        return SimpleNamespace(
            successes=[SimpleNamespace(source_reference=material_ids[0], local_path=Path(output_dir) / "mp-1.cif")],
            failures=[],
        )

    def fetch_properties(self, material_ids, names):
        return [SimpleNamespace(material_id=material_ids[0], properties={})]

    def search_substrates(self, material_ids):
        return [{"material_id": material_ids[0], "substrate_id": "mp-2"}]


def test_mp_cli_commands_use_collector_boundary(monkeypatch, tmp_path: Path, capsys):
    import llm_matgen.sources.mp as mp_module
    from llm_matgen.__main__ import main

    monkeypatch.setattr(mp_module, "MPCollector", FakeCollector)
    monkeypatch.setenv("MP_API_KEY", "fake")
    monkeypatch.chdir(tmp_path)

    assert main(["search", "--formula", "Si", "--limit", "5"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["material_id"] == "mp-1"
    assert main(["download", "mp-1", "--output-dir", "downloads"]) == 0
    assert json.loads(capsys.readouterr().out)["successes"][0]["material_id"] == "mp-1"
    assert main(["properties", "mp-1", "--property", "thermo"]) == 0
    assert json.loads(capsys.readouterr().out)["materials"][0]["material_id"] == "mp-1"
    assert main(["substrates", "mp-1"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["substrate_id"] == "mp-2"
