import json
from pathlib import Path


def test_adsorption_artifact_package_writes_auditable_json_and_hash(tmp_path: Path):
    from llm_matgen.adsorption.package import write_adsorption_artifacts

    artifacts = write_adsorption_artifacts(
        tmp_path,
        references={"slab": {"formula": "Cu4"}, "molecule": {"formula": "H2"}, "parent": {"id": "p1"}},
        retrieval_trace={"fallback_reason": None},
        validation={"valid": True},
        dft_handoff={"vacuum_axis": 2},
    )
    assert {item.kind for item in artifacts} == {"references", "retrieval", "validation", "dft_handoff"}
    for item in artifacts:
        assert len(item.sha256) == 64
        assert json.loads(item.path.read_text(encoding="utf-8"))


def test_pipeline_accepts_narrow_artifact_contributor(tmp_path: Path):
    from llm_matgen.adsorption.package import write_adsorption_artifacts
    from llm_matgen.pipeline import GenerationPipeline
    from llm_matgen.io.exporters import ExportOptions

    class Generator:
        def generate(self, structure, params):
            from llm_matgen.generators.models import GenerationResult
            return GenerationResult()

    seen = []
    def contributor(run_dir, input_structure, generation):
        result = write_adsorption_artifacts(run_dir, references={"input": "ok"}, retrieval_trace={}, validation={}, dft_handoff={})
        seen.extend(result)
        return result

    pipeline = GenerationPipeline(tmp_path)
    result = pipeline.run(Generator(), None, object(), ExportOptions(), run_id="run-artifacts", artifact_contributor=contributor)
    assert result.manifest_path.exists()
    assert len(seen) == 4
    assert "adsorption" in result.manifest_path.read_text(encoding="utf-8")
