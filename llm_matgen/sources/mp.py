"""Materials Project client boundary with dependency injection and stable errors."""

from __future__ import annotations

import os
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, NonNegativeFloat, PositiveInt, model_validator
from pymatgen.core import Structure
from pymatgen.io.cif import CifWriter

from llm_matgen.io.readers import StructureReadError, read_structure
from llm_matgen.sources.models import SourceStructure
from llm_matgen.utils.structure import structure_sha256


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


@dataclass
class MPDownloadFailure:
    material_id: str
    error_type: str
    message: str


@dataclass
class MPDownloadResult:
    successes: list[SourceStructure] = field(default_factory=list)
    failures: list[MPDownloadFailure] = field(default_factory=list)


class PropertyValue(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: Any | None = None
    available: bool
    endpoint: str
    method: str | None = None
    error: str | None = None


class MaterialProperties(BaseModel):
    material_id: str
    properties: dict[str, PropertyValue]


def _default_client_factory(api_key: str):
    from mp_api.client import MPRester

    return MPRester(api_key)


T = TypeVar("T")


class MPCollector:
    PROPERTY_ENDPOINTS = {
        "thermo": "thermo",
        "electronic": "electronic_structure",
        "magnetism": "magnetism",
        "dielectric": "dielectric",
        "phonon": "phonon",
        "elasticity": "elasticity",
    }
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

    def download(self, material_ids: list[str], output_dir: Path) -> MPDownloadResult:
        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        result = MPDownloadResult()
        for material_id in material_ids:
            try:
                self._validate_material_id(material_id)
                reusable = self._load_reusable_download(material_id, destination)
                if reusable is not None:
                    result.successes.append(reusable)
                    continue
                document = self.execute(
                    lambda client, mid=material_id: self._fetch_download_document(client, mid)
                )
                result.successes.append(
                    self._write_download(material_id, document, destination)
                )
            except Exception as exc:
                mapped = exc if isinstance(exc, MPError) else self._map_error(exc)
                result.failures.append(
                    MPDownloadFailure(
                        material_id=material_id,
                        error_type=type(mapped).__name__,
                        message=str(mapped),
                    )
                )
        return result

    def fetch_properties(
        self,
        material_ids: list[str],
        property_names: list[str],
    ) -> list[MaterialProperties]:
        unknown = sorted(set(property_names).difference(self.PROPERTY_ENDPOINTS))
        if unknown:
            raise MPDataError(f"unknown Materials Project properties: {', '.join(unknown)}")
        by_material: dict[str, dict[str, PropertyValue]] = {
            material_id: {} for material_id in material_ids
        }
        for property_name in property_names:
            endpoint_name = self.PROPERTY_ENDPOINTS[property_name]
            endpoint_label = f"materials.{endpoint_name}"
            try:
                documents = self.execute(
                    lambda client, name=endpoint_name: list(
                        getattr(client.materials, name).search(material_ids=material_ids)
                    )
                )
                indexed = {
                    str(self._document_value(document, "material_id")): document
                    for document in documents
                    if self._document_value(document, "material_id") is not None
                }
                for material_id in material_ids:
                    document = indexed.get(material_id)
                    if document is None:
                        by_material[material_id][property_name] = PropertyValue(
                            available=False,
                            endpoint=endpoint_label,
                        )
                        continue
                    method = self._document_value(document, "method")
                    by_material[material_id][property_name] = PropertyValue(
                        value=document,
                        available=True,
                        endpoint=endpoint_label,
                        method=str(method) if method is not None else None,
                    )
            except MPError as exc:
                for material_id in material_ids:
                    by_material[material_id][property_name] = PropertyValue(
                        available=False,
                        endpoint=endpoint_label,
                        error=str(exc),
                    )
        return [
            MaterialProperties(material_id=material_id, properties=by_material[material_id])
            for material_id in material_ids
        ]

    def search_substrates(self, material_ids: list[str]) -> list[Any]:
        return self._special_query("substrates", material_ids)

    def search_grain_boundaries(self, material_ids: list[str]) -> list[Any]:
        return self._special_query("grain_boundaries", material_ids)

    def _special_query(self, endpoint_name: str, material_ids: list[str]) -> list[Any]:
        return self.execute(
            lambda client: list(
                getattr(client.materials, endpoint_name).search(material_ids=material_ids)
            )
        )

    @staticmethod
    def _validate_material_id(material_id: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", material_id) is None or ".." in material_id:
            raise MPDataError("invalid Materials Project material ID")

    @staticmethod
    def _fetch_download_document(client, material_id: str):
        documents = client.materials.summary.search(
            material_ids=[material_id],
            fields=["material_id", "structure", "database_version", "last_updated"],
            chunk_size=1,
            num_chunks=1,
        )
        documents = list(documents)
        if len(documents) != 1:
            raise MPDataError(f"expected one Materials Project structure for {material_id}")
        return documents[0]

    @staticmethod
    def _document_value(document, name: str, default=None):
        return document.get(name, default) if isinstance(document, dict) else getattr(document, name, default)

    def _load_reusable_download(
        self,
        material_id: str,
        destination: Path,
    ) -> SourceStructure | None:
        cif_path = destination / f"{material_id}.cif"
        metadata_path = cif_path.with_suffix(".json")
        if not cif_path.is_file() or not metadata_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            structure = read_structure(cif_path, fmt="cif")
            actual_hash = structure_sha256(structure)
            if metadata.get("structure_hash") != actual_hash:
                return None
            retrieved_at = datetime.fromisoformat(metadata["retrieved_at"])
        except (OSError, ValueError, KeyError, StructureReadError):
            return None
        return SourceStructure(
            artifact_id=material_id,
            source_kind="materials-project",
            source_reference=material_id,
            structure_hash=actual_hash,
            database_version=metadata.get("database_version"),
            retrieved_at=retrieved_at,
            local_path=cif_path,
            structure=structure,
        )

    def _write_download(self, material_id: str, document, destination: Path) -> SourceStructure:
        structure = self._document_value(document, "structure")
        if not isinstance(structure, Structure):
            raise MPDataError(f"Materials Project response for {material_id} has no valid structure")
        response_id = str(self._document_value(document, "material_id", ""))
        if response_id != material_id:
            raise MPDataError(f"Materials Project returned {response_id!r} for {material_id}")
        database_version = self._document_value(document, "database_version")
        if database_version is None:
            database_version = self._document_value(document, "last_updated")
        if database_version is not None:
            database_version = str(database_version)
        retrieved_at = datetime.now(timezone.utc)
        structure_hash = structure_sha256(structure)
        cif_path = self._next_download_path(destination, material_id)
        metadata_path = cif_path.with_suffix(".json")
        cif_temp = cif_path.with_suffix(cif_path.suffix + ".tmp")
        metadata_temp = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        metadata = {
            "material_id": material_id,
            "structure_hash": structure_hash,
            "database_version": database_version,
            "retrieved_at": retrieved_at.isoformat(),
        }
        try:
            CifWriter(structure).write_file(cif_temp)
            metadata_temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            os.replace(cif_temp, cif_path)
            os.replace(metadata_temp, metadata_path)
        except Exception:
            cif_temp.unlink(missing_ok=True)
            metadata_temp.unlink(missing_ok=True)
            if cif_path.exists() and not metadata_path.exists():
                cif_path.unlink(missing_ok=True)
            raise
        restored = read_structure(cif_path, fmt="cif")
        restored_hash = structure_sha256(restored)
        if restored_hash != structure_hash:
            raise MPDataError("downloaded CIF round-trip changed the structure hash")
        return SourceStructure(
            artifact_id=material_id,
            source_kind="materials-project",
            source_reference=material_id,
            structure_hash=restored_hash,
            database_version=database_version,
            retrieved_at=retrieved_at,
            local_path=cif_path,
            structure=restored,
        )

    @staticmethod
    def _next_download_path(destination: Path, material_id: str) -> Path:
        base = destination / f"{material_id}.cif"
        if not base.exists() and not base.with_suffix(".json").exists():
            return base
        version = 2
        while True:
            candidate = destination / f"{material_id}-v{version}.cif"
            if not candidate.exists() and not candidate.with_suffix(".json").exists():
                return candidate
            version += 1

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
