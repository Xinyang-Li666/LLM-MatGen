from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    case_id: str
    revision_id: str
    status: str = "eligible"
    completeness: float = 1.0
    features: dict = None
    index_revision: int = 1


def _candidates():
    return [
        Candidate("b", "r-b", features={"anchor_element": "O", "surface_side": "top", "height": 2.0}),
        Candidate("a", "r-a", features={"anchor_element": "O", "surface_side": "top", "height": 2.1}),
        Candidate("c", "r-c", features={"anchor_element": "C", "surface_side": "bottom", "height": 3.0}),
    ]


def test_query_applies_strict_chemistry_filter_and_stable_sorting():
    from llm_matgen.adsorption.retrieval import RetrievalEngine, RetrievalQuery

    result = RetrievalEngine().query(
        _candidates(), RetrievalQuery(anchor_element="O", surface_side="top", top_k=2)
    )

    assert [match.case_id for match in result.matches] == ["a", "b"]
    assert all(match.score >= 0 for match in result.matches)
    assert result.trace.fallback_reason is None


def test_query_respects_completeness_threshold_and_index_revision():
    from llm_matgen.adsorption.retrieval import RetrievalEngine, RetrievalQuery

    candidates = [Candidate("old", "r-old", completeness=0.4, index_revision=1), Candidate("new", "r-new", index_revision=2)]
    result = RetrievalEngine().query(candidates, RetrievalQuery(min_completeness=0.8, index_revision=1))

    assert result.matches == ()
    assert result.trace.fallback_reason == "no_complete_match_at_index_revision"


def test_query_reports_missing_component_and_does_not_relax_filter():
    from llm_matgen.adsorption.retrieval import RetrievalEngine, RetrievalQuery

    result = RetrievalEngine().query(
        [Candidate("a", "r-a", features={"surface_side": "top"})],
        RetrievalQuery(anchor_element="O"),
    )

    assert result.matches == ()
    assert result.trace.fallback_reason == "required_component_missing"
