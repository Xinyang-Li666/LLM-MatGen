from pathlib import Path

import pytest


CASES = [
    ("vacancy", ["--input", "in.cif", "--target-element", "Co", "--count", "1"]),
    ("interstitial", ["--input", "in.cif", "--element", "H", "--count", "1"]),
    ("doping", ["--input", "in.cif", "--target-element", "Co", "--dopant-element", "Ni", "--count", "1"]),
    ("solid-solution", ["--input", "in.cif", "--target-element", "Co", "--substituent", "Ni=1"]),
    ("surface", ["--input", "in.cif", "--miller", "0,0,1", "--slab-size", "5", "--vacuum-size", "8"]),
    ("grain-boundary", ["--input", "in.cif", "--rotation-axis", "0,0,1", "--angle", "36.87"]),
    ("interface", ["--film", "film.cif", "--substrate", "sub.cif", "--film-miller", "0,0,1", "--substrate-miller", "0,0,1", "--film-thickness", "5", "--substrate-thickness", "5", "--vacuum-thickness", "8", "--gap", "2"]),
    ("stacking-fault", ["--input", "in.cif", "--plane", "0,0,1", "--slip-vector", "0.1,0,0"]),
    ("dislocation", ["--input", "in.cif", "--line-direction", "0,0,1", "--burgers-vector", "0,0,1", "--slip-plane", "1,0,0", "--character", "screw", "--core-position", "0.5,0.5", "--radius", "10", "--poisson-ratio", "0.3"]),
    ("adsorption", ["--slab", "slab.cif", "--adsorbate", "adsorbate.xyz", "--anchor-index", "1", "--site-type", "top"]),
]


@pytest.mark.parametrize("name,arguments", CASES)
def test_ten_generate_commands_parse_into_requests(tmp_path: Path, monkeypatch, name, arguments):
    from llm_matgen.__main__ import build_generation_request, build_parser

    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(
        ["generate", name, *arguments, "--format", "cif", "--format", "lammps-data", "--output-root", "runs"]
    )
    request = build_generation_request(args)
    assert request.generator == name
    assert request.export_options.formats[0].value == "cif"
    assert request.export_options.formats[1].value == "lammps-data"
    assert request.limits.output_root == (tmp_path / "runs").resolve()


def test_generate_parses_percent_seed_and_defaults_to_poscar(tmp_path: Path, monkeypatch):
    from llm_matgen.__main__ import build_generation_request, build_parser

    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(
        ["generate", "vacancy", "--input", "in.cif", "--target-element", "Co", "--concentration", "5%", "--seed", "7"]
    )
    request = build_generation_request(args)
    assert request.parameters["concentration"] == 0.05
    assert request.parameters["seed"] == 7
    assert [item.value for item in request.export_options.formats] == ["poscar"]


def test_adsorption_request_and_viewer_flags_are_typed(tmp_path: Path, monkeypatch):
    from llm_matgen.__main__ import build_generation_request, build_parser

    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args([
        "generate", "adsorption", "--slab", "slab.cif", "--adsorbate", "OH.xyz",
        "--anchor-index", "1", "--reference-axis", "0,0,1", "--site-type", "top",
        "--site-type", "bridge", "--no-viewer",
    ])
    request = build_generation_request(args)
    assert request.input_refs == ["slab.cif", "OH.xyz"]
    assert request.parameters["anchor_index"] == 1
    assert request.parameters["site_types"] == ["top", "bridge"]
    assert request.viewer is False


def test_solid_solution_exposes_sqs_iterations(tmp_path: Path, monkeypatch):
    from llm_matgen.__main__ import build_generation_request, build_parser

    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args([
        "generate", "solid-solution", "--input", "in.cif",
        "--target-element", "Co", "--substituent", "Ni=1",
        "--method", "sqs", "--sqs-iterations", "10",
    ])
    request = build_generation_request(args)

    assert request.parameters["sqs_iterations"] == 10


def test_generate_rejects_output_root_escape(tmp_path: Path, monkeypatch):
    from llm_matgen.__main__ import build_generation_request, build_parser

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    args = build_parser().parse_args(
        ["generate", "vacancy", "--input", "in.cif", "--target-element", "Co", "--count", "1", "--output-root", "../escape"]
    )
    with pytest.raises(ValueError, match="output root"):
        build_generation_request(args)


def test_vacancy_cli_runs_service_with_default_check_and_manifest(tmp_path: Path, monkeypatch, capsys):
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter
    from llm_matgen.__main__ import main

    monkeypatch.chdir(tmp_path)
    structure = Structure(
        Lattice.cubic(4.2), ["Co", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )
    CifWriter(structure).write_file("input.cif")
    code = main([
        "generate", "vacancy", "--input", "input.cif",
        "--target-element", "Co", "--count", "1", "--seed", "7",
        "--output-root", "runs",
    ])
    assert code == 0
    assert list((tmp_path / "runs").glob("*/manifest.json"))
    assert '"ok": true' in capsys.readouterr().out


def test_all_nine_cli_workflows_reach_generation_service_offline(tmp_path: Path, monkeypatch, capsys):
    from types import SimpleNamespace
    import llm_matgen.services.generation as service_module
    from llm_matgen.__main__ import main

    captured = []

    class FakeService:
        def __init__(self, source):
            pass

        def run(self, request):
            captured.append(request.generator)
            manifest = request.limits.output_root / request.generator / "manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text('{"responsibility_disclaimer":"generation only"}', encoding="utf-8")
            run = SimpleNamespace(
                generation=SimpleNamespace(generated_count=1),
                manifest_path=manifest,
                errors=[],
            )
            return SimpleNamespace(ok=True, runs=[run])

    monkeypatch.setattr(service_module, "GenerationService", FakeService)
    monkeypatch.chdir(tmp_path)
    for name, arguments in CASES:
        code = main([
            "generate", name, *arguments,
            "--output-root", f"runs-{name}",
        ])
        assert code == 0
        payload = __import__("json").loads(capsys.readouterr().out)
        assert Path(payload["runs"][0]["manifest"]).exists()
    assert captured == [name for name, _ in CASES]
