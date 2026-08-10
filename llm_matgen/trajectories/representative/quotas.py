"""Deterministic source quota allocation."""

from __future__ import annotations

from collections.abc import Mapping


def allocate_proportional_quotas(
    source_counts: Mapping[str, int],
    target_count: int,
) -> dict[str, int]:
    """Allocate a target count by source size using largest remainders."""

    if isinstance(target_count, bool) or int(target_count) != target_count or int(target_count) <= 0:
        raise ValueError("target count must be positive")
    sizes = {str(name): int(count) for name, count in source_counts.items() if int(count) > 0}
    if not sizes:
        return {}
    budget = min(int(target_count), sum(sizes.values()))
    if budget < len(sizes):
        raise ValueError(
            f"target count {budget} is smaller than the {len(sizes)} non-empty sources"
        )
    total_weight = float(sum(sizes.values()))
    raw = {name: budget * size / total_weight for name, size in sizes.items()}
    quotas = {name: min(size, int(value)) for name, (size, value) in
              ((name, (sizes[name], raw[name])) for name in sizes)}

    # Every non-empty source must contribute at least one frame whenever the
    # requested budget can accommodate all sources.  The adjustment is kept
    # deterministic, then the remaining frames use largest remainders.
    for name in quotas:
        if quotas[name] == 0:
            quotas[name] = 1

    delta = budget - sum(quotas.values())
    if delta > 0:
        order = sorted(
            sizes,
            key=lambda name: (-(raw[name] - int(raw[name])), -sizes[name], name),
        )
        while delta:
            granted = False
            for name in order:
                if quotas[name] < sizes[name]:
                    quotas[name] += 1
                    delta -= 1
                    granted = True
                    if not delta:
                        break
            if not granted:
                break
    elif delta < 0:
        order = sorted(
            sizes,
            key=lambda name: ((raw[name] - int(raw[name])), sizes[name], name),
        )
        while delta < 0:
            removed = False
            for name in order:
                if quotas[name] > 1:
                    quotas[name] -= 1
                    delta += 1
                    removed = True
                    if not delta:
                        break
            if not removed:
                break
    return quotas
