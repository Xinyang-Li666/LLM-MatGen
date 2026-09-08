import json
from dataclasses import dataclass
from datetime import datetime, timezone

from pymatgen.core import Lattice, Structure


def _structure():
    return Structure(Lattice.cubic(5), ["Si", "Si"], [[0, 0, 0], [0.5, 0.5, 0.5]])


@dataclass
class _Generator:
    count: int = 1

    def generate(self, structure, params):
        from llm_matgen.generators.models import GeneratedStructure, GenerationResult, Provenance, StructureRecord

        generated = []
        for index in range(self.count):
            child = structure.copy()
            child.translate_sites([1], [0.05 * index, 0, 0], frac_coords=True, to_unit_cell=True)
            identifier = f"child-{index}"
            generated.append(GeneratedStructure(child, StructureRecord(
                structure_id=identifier, parent_structure_id="parent", formula=child.composition.reduced_formula,
                n_atoms=len(child), actual_parameters={}, site_mapping={},
            )))
        return GenerationResult(
            defect_type="test", input_count=1, generated=generated,
            provenance=Provenance(
                generator="test", generator_version="test", input_source="fixture",
                input_structure_hash="parent", parameters={}, seed=None,
                created_at=datetime.now(timezone.utc),
            ),
        )


def test_pipeline_generates_one_registered_viewer_for_exported_candidates(tmp_path):
    from llm_matgen.io.exporters import ExportOptions
    from llm_matgen.pipeline import GenerationPipeline

    result = GenerationPipeline(tmp_path).run(_Generator(2), _structure(), {}, ExportOptions(), run_id="viewer-run")
    assert result.ok
    assert result.viewer_path == tmp_path / "viewer-run" / "viewer.html"
    assert result.viewer_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    viewers = [item for item in manifest["artifacts"] if item["format"] == "html"]
    assert len(viewers) == 1
    assert viewers[0]["path"] == "viewer.html"


def test_pipeline_can_disable_viewer(tmp_path):
    from llm_matgen.io.exporters import ExportOptions
    from llm_matgen.pipeline import GenerationPipeline

    result = GenerationPipeline(tmp_path).run(_Generator(), _structure(), {}, ExportOptions(), run_id="no-viewer", viewer=False)
    assert result.ok
    assert result.viewer_path is None
    assert not (tmp_path / "no-viewer" / "viewer.html").exists()


def test_viewer_failure_is_warning_and_does_not_lose_exported_structures(tmp_path, monkeypatch):
    import llm_matgen.viewer
    from llm_matgen.io.exporters import ExportOptions
    from llm_matgen.pipeline import GenerationPipeline

    monkeypatch.setattr(llm_matgen.viewer, "write_viewer", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("preview budget exceeded")))
    result = GenerationPipeline(tmp_path).run(_Generator(), _structure(), {}, ExportOptions(), run_id="viewer-warning")
    assert result.ok
    assert result.viewer_path is None
    assert result.artifacts[0].path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert any("preview budget exceeded" in warning for warning in manifest["warnings"])
