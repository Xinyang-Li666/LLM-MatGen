"""Configuration objects for descriptor-based trajectory sampling."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class ReductionConfig:
    method: str = "randomized-pca"
    max_components: int = 64
    variance_target: float = 0.99
    fit_sample_count: int = 10000
    seed: int = 42
    whiten: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ReductionConfig":
        values = dict(data or {})
        result = cls(**{key: values[key] for key in values if key in {
            "method", "max_components", "variance_target", "fit_sample_count", "seed", "whiten",
        }})
        if result.method != "randomized-pca":
            raise ValueError("reduction method must be randomized-pca")
        if result.max_components <= 0:
            raise ValueError("max_components must be positive")
        if not 0 < result.variance_target <= 1:
            raise ValueError("variance_target must be in (0, 1]")
        if result.fit_sample_count <= 0:
            raise ValueError("fit_sample_count must be positive")
        return result


@dataclass(frozen=True)
class RDFSamplingConfig:
    r_min: float = 0.8
    r_max: float = 6.0
    bin_width: float = 0.05
    profile: str = "hybrid"
    reduction: ReductionConfig = ReductionConfig()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RDFSamplingConfig":
        values = dict(data or {})
        reduction = ReductionConfig.from_dict(values.get("reduction"))
        result = cls(
            r_min=float(values.get("r_min", cls.r_min)),
            r_max=float(values.get("r_max", cls.r_max)),
            bin_width=float(values.get("bin_width", cls.bin_width)),
            profile=str(values.get("profile", cls.profile)),
            reduction=reduction,
        )
        if result.r_min < 0 or result.r_max <= result.r_min:
            raise ValueError("r_max must be greater than r_min")
        if result.bin_width <= 0:
            raise ValueError("bin_width must be positive")
        if result.profile not in {"hybrid", "grouped", "full"}:
            raise ValueError("profile must be hybrid, grouped, or full")
        return result


def merge_sampling_config(base: RDFSamplingConfig, overrides: dict[str, Any]) -> RDFSamplingConfig:
    """Merge explicit values over a validated RDF configuration."""

    values = dict(overrides)
    reduction_values = values.pop("reduction", None)
    merged = replace(base, **{key: values[key] for key in values if key in {
        "r_min", "r_max", "bin_width", "profile",
    }})
    if reduction_values is not None:
        merged = replace(merged, reduction=ReductionConfig.from_dict({
            "method": base.reduction.method,
            "max_components": base.reduction.max_components,
            "variance_target": base.reduction.variance_target,
            "fit_sample_count": base.reduction.fit_sample_count,
            "seed": base.reduction.seed,
            "whiten": base.reduction.whiten,
            **dict(reduction_values),
        }))
    return RDFSamplingConfig.from_dict({
        "r_min": merged.r_min,
        "r_max": merged.r_max,
        "bin_width": merged.bin_width,
        "profile": merged.profile,
        "reduction": {
            "method": merged.reduction.method,
            "max_components": merged.reduction.max_components,
            "variance_target": merged.reduction.variance_target,
            "fit_sample_count": merged.reduction.fit_sample_count,
            "seed": merged.reduction.seed,
            "whiten": merged.reduction.whiten,
        },
    })


@dataclass(frozen=True)
class SOAPConfig:
    backend: str = "dscribe"
    r_cut: float = 5.0
    n_max: int = 6
    l_max: int = 4
    sigma: float = 0.5
    rbf: str = "gto"
    compression: str = "mu1nu1"
    pooling: str = "category-mean-std"
    periodic: bool = True
    dtype: str = "float32"
    groups: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.backend != "dscribe" or self.r_cut <= 0 or self.n_max <= 0 or self.l_max < 0 or self.sigma <= 0:
            raise ValueError("invalid SOAP backend or positive parameters")
        if self.rbf not in {"gto", "polynomial"} or self.compression not in {"mu1nu1", "crossover"}:
            raise ValueError("unsupported SOAP rbf or compression")
        if self.pooling not in {"category-mean-std", "mean-std", "mean"} or self.dtype not in {"float32", "float64"}:
            raise ValueError("unsupported SOAP pooling or dtype")
        groups = {str(name): tuple(int(z) for z in values) for name, values in self.groups.items()}
        if any(not name or not values for name, values in groups.items()):
            raise ValueError("SOAP groups must contain non-empty categories")
        flattened = [z for values in groups.values() for z in values]
        if any(z < 1 or z > 118 for z in flattened) or len(flattened) != len(set(flattened)):
            raise ValueError("SOAP group elements must be valid and non-overlapping")
        object.__setattr__(self, "groups", groups)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SOAPConfig":
        if data is None:
            return cls()
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"unknown SOAP configuration fields: {sorted(unknown)}")
        return cls(**data)
