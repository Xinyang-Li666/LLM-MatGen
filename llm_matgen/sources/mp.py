"""Materials Project client boundary with dependency injection and stable errors."""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any, Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, NonNegativeFloat, PositiveInt, model_validator


class MPError(RuntimeError):
    """Base class for Materials Project boundary failures."""


class MPAuthenticationError(MPError):
    pass


class MPRateLimitError(MPError):
    pass


class MPUnavailableError(MPError):
    pass


class MPDataError(MPError):
    pass


class MPClientFactory(Protocol):
    def __call__(self, api_key: str) -> Any: ...


class MaterialSearchQuery(BaseModel):
    elements: list[str] | None = None
    chemsys: str | None = None
    formula: str | None = None
    material_ids: list[str] | None = None
    n_elements: PositiveInt | None = None
    formation_energy_max: float | None = None
    band_gap_min: NonNegativeFloat | None = None
    band_gap_max: NonNegativeFloat | None = None
    structure_class: Literal["layered", "perovskite", "spinel", "rocksalt", "fluorite"] | None = None
    limit: PositiveInt = 100

    @model_validator(mode="after")
    def validate_query(self):
        if not any(
            value is not None
            for value in (
                self.elements,
                self.chemsys,
                self.formula,
                self.material_ids,
                self.n_elements,
                self.formation_energy_max,
                self.band_gap_min,
                self.band_gap_max,
            )
        ):
            raise ValueError("at least one server-side search criterion is required")
        if (
            self.band_gap_min is not None
            and self.band_gap_max is not None
            and self.band_gap_min > self.band_gap_max
        ):
            raise ValueError("band gap minimum cannot exceed maximum")
        return self


class MaterialSummary(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    material_id: str
    formula_pretty: str | None = None
    formation_energy_per_atom: float | None = None
    band_gap: float | None = None
    structure: Any | None = None


def _default_client_factory(api_key: str):
    from mp_api.client import MPRester

    return MPRester(api_key)


T = TypeVar("T")


class MPCollector:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        client_factory: MPClientFactory | None = None,
    ):
        self._api_key = api_key or os.environ.get("MP_API_KEY")
        if not self._api_key:
            raise MPAuthenticationError(
                "Materials Project API key is required; set MP_API_KEY or pass api_key"
            )
        self.client_factory = client_factory or _default_client_factory
        self.max_results = 1000

    def execute(self, operation: Callable[[Any], T]) -> T:
        try:
            client = self.client_factory(self._api_key)
            manager = client if hasattr(client, "__enter__") else nullcontext(client)
            with manager as active_client:
                return operation(active_client)
        except MPError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

    def search(self, query: MaterialSearchQuery) -> list[MaterialSummary]:
        if query.limit > self.max_results:
            raise MPDataError(
                f"search limit {query.limit} exceeds system limit {self.max_results}"
            )
        criteria: dict[str, Any] = {}
        for name in ("elements", "chemsys", "formula", "material_ids"):
            value = getattr(query, name)
            if value is not None:
                criteria[name] = value
        if query.n_elements is not None:
            criteria["num_elements"] = query.n_elements
        if query.formation_energy_max is not None:
            criteria["formation_energy"] = (None, query.formation_energy_max)
        if query.band_gap_min is not None or query.band_gap_max is not None:
            criteria["band_gap"] = (query.band_gap_min, query.band_gap_max)
        criteria["chunk_size"] = min(100, query.limit)
        criteria["num_chunks"] = None

        def collect(client) -> list[MaterialSummary]:
            documents = client.materials.summary.search(**criteria)
            results: list[MaterialSummary] = []
            for document in documents:
                raw = document if isinstance(document, dict) else {
                    name: getattr(document, name, None)
                    for name in (
                        "material_id",
                        "formula_pretty",
                        "formation_energy_per_atom",
                        "band_gap",
                        "structure",
                    )
                }
                if not raw.get("material_id"):
                    raise MPDataError("Materials Project summary is missing material_id")
                results.append(MaterialSummary.model_validate(raw))
                if len(results) >= self.max_results:
                    break
            results.sort(key=lambda item: item.material_id)
            return results[: query.limit]

        return self.execute(collect)

    @staticmethod
    def _map_error(exc: Exception) -> MPError:
        response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
        if status in {401, 403}:
            return MPAuthenticationError("Materials Project authentication failed")
        if status == 429:
            return MPRateLimitError("Materials Project rate limit exceeded")
        if isinstance(exc, (TimeoutError, ConnectionError)) or (
            isinstance(status, int) and status >= 500
        ):
            return MPUnavailableError("Materials Project service is unavailable")
        return MPDataError("Materials Project returned malformed or unusable data")
