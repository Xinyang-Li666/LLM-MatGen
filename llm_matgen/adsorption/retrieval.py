"""Deterministic, non-learning retrieval of audited adsorption histories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RetrievalQuery:
    anchor_element: str | None = None
    surface_side: str | None = None
    min_completeness: float = 0.0
    index_revision: int | None = None
    top_k: int = 10


@dataclass(frozen=True)
class RetrievalMatch:
    case_id: str
    revision_id: str
    score: float
    completeness: float
    score_components: dict[str, float]


@dataclass(frozen=True)
class RetrievalTrace:
    candidate_count: int
    filtered_count: int
    fallback_reason: str | None


@dataclass(frozen=True)
class RetrievalResult:
    matches: tuple[RetrievalMatch, ...]
    trace: RetrievalTrace


class RetrievalEngine:
    def query(self, candidates: Iterable[Any], query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0.0 <= query.min_completeness <= 1.0:
            raise ValueError("min_completeness must be between 0 and 1")
        items = list(candidates)
        filtered = []
        missing_component = False
        for candidate in items:
            if getattr(candidate, "status", "eligible") != "eligible":
                continue
            if query.index_revision is not None and getattr(candidate, "index_revision", 0) > query.index_revision:
                continue
            completeness = float(getattr(candidate, "completeness", 0.0))
            if completeness < query.min_completeness:
                continue
            features = getattr(candidate, "features", None) or {}
            if query.anchor_element is not None:
                if "anchor_element" not in features:
                    missing_component = True
                    continue
                if features["anchor_element"] != query.anchor_element:
                    continue
            if query.surface_side is not None:
                if "surface_side" not in features:
                    missing_component = True
                    continue
                if features["surface_side"] != query.surface_side:
                    continue
            filtered.append((candidate, completeness))
        matches = [
            RetrievalMatch(
                case_id=str(candidate.case_id),
                revision_id=str(candidate.revision_id),
                score=1.0,
                completeness=completeness,
                score_components={"chemistry": 1.0, "geometry": 1.0},
            )
            for candidate, completeness in filtered
        ]
        matches.sort(key=lambda item: (-item.score, -item.completeness, item.case_id, item.revision_id))
        matches = matches[: query.top_k]
        reason = None
        if not matches:
            if missing_component:
                reason = "required_component_missing"
            elif query.min_completeness > 0 or query.index_revision is not None:
                reason = "no_complete_match_at_index_revision"
            else:
                reason = "no_match"
        return RetrievalResult(
            matches=tuple(matches),
            trace=RetrievalTrace(len(items), len(filtered), reason),
        )
