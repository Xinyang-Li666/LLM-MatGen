"""Two-pass streaming trajectory filtering engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
from typing import Callable, Iterable

from .cell import check_cell
from .config import FilterConfig
from .coordination import check_coordination
from .force import check_force
from .models import FilterFrame
from .numeric import check_frame
from .overlap import check_overlap
from .profiles import ThresholdProfile, calibrate_profile
from .writers import FilterWriters


@dataclass(frozen=True)
class FilterRunResult:
    run_dir: Path
    total: int
    clean: int
    anomalous: int
    not_evaluated: tuple[str, ...]
    reasons: dict[str, int]
    clean_path: Path
    anomalous_path: Path
    review_path: Path
    summary_path: Path
    profile_path: Path | None


class FilterEngine:
    def __init__(self, config: FilterConfig, profile: ThresholdProfile | None = None) -> None:
        self.config = config
        self.profile = profile

    def _run_dir(self, output_root: Path) -> Path:
        output_root = Path(output_root).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        for _ in range(10):
            path = output_root / f"filter-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
            try:
                path.mkdir()
                return path
            except FileExistsError:
                continue
        raise RuntimeError("could not allocate a unique filter output directory")

    def run(
        self,
        reader_factory: Callable[[], Iterable[FilterFrame]],
        output_root: Path,
        reference_factory: Callable[[], Iterable[FilterFrame]] | None = None,
        output_format: str = "extxyz",
    ) -> FilterRunResult:
        profile = self.profile
        if profile is None and reference_factory is not None and ({"force", "coordination"} & set(self.config.checks)):
            profile = calibrate_profile(reference_factory, self.config)
        run_dir = self._run_dir(output_root)
        profile_path = run_dir / "threshold-profile.json" if profile is not None else None
        if profile is not None:
            profile.write(profile_path)
        writers = FilterWriters(run_dir, output_format)
        total = clean = anomalous = 0
        reasons: dict[str, int] = {}
        not_evaluated: set[str] = set()
        reference_numbers = None if profile is None or not profile.reference_numbers else profile.reference_numbers
        completed = False
        try:
            for frame in reader_factory():
                total += 1
                if reference_numbers is None:
                    reference_numbers = tuple(sorted(int(z) for z in frame.atomic_numbers))
                results = [check_frame(frame, reference_numbers, self.config.allow_variable_composition)]
                hard_invalid = results[0].status == "fail"
                if not hard_invalid and "overlap" in self.config.checks:
                    results.append(check_overlap(
                        frame, overlap_scale=self.config.overlap_scale,
                        absolute_floor=self.config.overlap_floor, overlap_ratio=self.config.overlap_ratio,
                        pair_min_distance=self.config.pair_min_distance,
                    ))
                if not hard_invalid and "force" in self.config.checks:
                    threshold = self.config.force_max if self.config.force_max is not None else (profile.force_threshold if profile else None)
                    results.append(check_force(frame, threshold))
                if not hard_invalid and "coordination" in self.config.checks:
                    results.append(check_coordination(
                        frame,
                        bounds=profile.coordination_bounds if profile else None,
                        groups={k: list(v) for k, v in profile.coordination_groups.items()} if profile else self.config.coord_groups,
                        cutoff=self.config.coord_cutoff,
                    ))
                if not hard_invalid and "cell" in self.config.checks:
                    results.append(check_cell(frame))
                for result in results:
                    if result.status == "not_evaluated":
                        not_evaluated.add(result.detector)
                    if result.status == "fail":
                        for reason in result.reasons:
                            reasons[reason] = reasons.get(reason, 0) + 1
                is_anomalous = any(result.status == "fail" for result in results)
                if is_anomalous:
                    anomalous += 1
                else:
                    clean += 1
                writers.write_frame(frame, is_anomalous, {
                    "source_index": frame.source_index,
                    "timestep": frame.timestep,
                    "anomalous": is_anomalous,
                    "reasons": [reason for result in results for reason in result.reasons],
                    "results": [
                        {"detector": result.detector, "status": result.status,
                         "severity": result.severity, "metrics": result.metrics}
                        for result in results
                    ],
                })
            completed = True
        finally:
            writers.close(success=completed)
        summary = {
            "schema_version": "1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total": total, "clean": clean, "anomalous": anomalous,
            "not_evaluated": sorted(not_evaluated), "reasons": reasons,
            "clean_path": str(writers.clean_path), "anomalous_path": str(writers.anomalous_path),
            "review_path": str(writers.review_path),
        }
        summary_path = run_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return FilterRunResult(
            run_dir=run_dir, total=total, clean=clean, anomalous=anomalous,
            not_evaluated=tuple(sorted(not_evaluated)), reasons=reasons,
            clean_path=writers.clean_path, anomalous_path=writers.anomalous_path,
            review_path=writers.review_path, summary_path=summary_path, profile_path=profile_path,
        )
