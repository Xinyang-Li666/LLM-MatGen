import json
from pathlib import Path

from pymatgen.core import Lattice, Structure


def test_adsorption_cli_uses_service_and_opens_only_created_viewer(tmp_path, monkeypatch, capsys):
    import webbrowser
    from llm_matgen.__main__ import main

    monkeypatch.chdir(tmp_path)
    slab = Structure(
        Lattice.from_parameters(4, 4, 14, 90, 90, 90), ["Cu"] * 4,
        [[0, 0, 0.4], [0.5, 0, 0.4], [0, 0.5, 0.4], [0.5, 0.5, 0.4]],
    )
    slab.to(filename="slab.cif")
    Path("H.xyz").write_text("1\nH\nH 0 0 0\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda uri: opened.append(uri))
    code = main([
        "generate", "adsorption", "--slab", "slab.cif", "--adsorbate", "H.xyz",
        "--site-type", "top", "--max-structures", "1", "--output-root", "runs", "--open",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["runs"][0]["viewer"].endswith("viewer.html")
    assert opened == [Path(payload["runs"][0]["viewer"]).resolve().as_uri()]
    assert payload["runs"][0]["structures"]
