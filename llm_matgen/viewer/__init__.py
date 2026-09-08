"""Safe, portable, offline previews of generated crystal structures."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html as html_module
from importlib.resources import files
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
from ase.data import atomic_numbers, covalent_radii
from scipy.spatial import cKDTree


RENDERER_VERSION = "2.0.4"
RENDERER_UPSTREAM = "https://github.com/3dmol/3Dmol.js"
RENDERER_SHA256 = "612eedd3ad7c36537813066d04f15a6e71285b9c59b364a6ab0296e39c67b7d1"
MAX_ATOMS_PER_STRUCTURE = 20_000
MAX_TOTAL_ATOMS = 200_000
MAX_NEIGHBORS_PER_ATOM = 512
MAX_LABEL_LENGTH = 200
MAX_SERIALIZED_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ViewerArtifact:
    path: Path
    sha256: str


def _assets():
    return files(__package__).joinpath("assets")


def renderer_metadata() -> dict[str, str]:
    asset_root = _assets()
    renderer = asset_root.joinpath("3Dmol-min.js").read_bytes()
    # Git may materialize this text asset with CRLF on Windows.  Verify the
    # repository-content hash so the integrity check is platform independent.
    digest = hashlib.sha256(renderer.replace(b"\r\n", b"\n")).hexdigest()
    if digest != RENDERER_SHA256:
        raise RuntimeError("packaged 3Dmol.js hash does not match the pinned renderer")
    return {
        "version": RENDERER_VERSION,
        "upstream": RENDERER_UPSTREAM,
        "sha256": digest,
        "license_text": asset_root.joinpath("3Dmol-LICENSE.txt").read_text(encoding="utf-8"),
    }


def _radius(symbol: str) -> float:
    try:
        radius = float(covalent_radii[atomic_numbers[symbol]])
    except (KeyError, IndexError, TypeError, ValueError):
        radius = 1.0
    return radius if np.isfinite(radius) and radius > 0 else 1.0


def structure_payload(label, structure) -> dict:
    """Return a JSON-safe, intra-cell ball-and-stick representation."""
    if not structure.is_ordered:
        raise ValueError("结构查看暂不支持部分占位，请先生成有序构型")
    coordinates = np.asarray(structure.cart_coords, dtype=float)
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    if not len(coordinates) or not np.isfinite(coordinates).all() or not np.isfinite(lattice).all():
        raise ValueError("结构查看需要非空且坐标、晶格有效的结构")
    if len(coordinates) > MAX_ATOMS_PER_STRUCTURE:
        raise ValueError(f"单个预览最多支持 {MAX_ATOMS_PER_STRUCTURE} 个原子")

    symbols = [site.specie.symbol for site in structure]
    radii = np.asarray([_radius(symbol) for symbol in symbols])
    bonds: list[list[int]] = [[] for _ in coordinates]
    tree = cKDTree(coordinates)
    max_radius = float(np.max(radii))
    for index, position in enumerate(coordinates):
        neighbors = tree.query_ball_point(position, 1.2 * (radii[index] + max_radius))
        if len(neighbors) > MAX_NEIGHBORS_PER_ATOM:
            raise ValueError("原子过于密集，无法安全生成球棍预览")
        for neighbor in neighbors:
            if neighbor <= index:
                continue
            distance = float(np.linalg.norm(position - coordinates[neighbor]))
            if 0.1 < distance <= 1.2 * (radii[index] + radii[neighbor]):
                bonds[index].append(neighbor)
                bonds[neighbor].append(index)

    movable = structure.site_properties.get("selective_dynamics", [[True] * 3] * len(coordinates))
    return {
        "label": str(label),
        "formula": structure.composition.reduced_formula,
        "cell": lattice.tolist(),
        "atoms": [
            {
                "element": symbol,
                "number": index + 1,
                "position": coordinates[index].tolist(),
                "bonds": bonds[index],
                "fixed": not any(bool(value) for value in movable[index]),
            }
            for index, symbol in enumerate(symbols)
        ],
    }


def write_viewer(structures, path: Path) -> ViewerArtifact:
    """Write one self-contained viewer without network or server dependencies."""
    entries = list(structures)
    if not entries:
        raise ValueError("预览需要至少一个候选结构")
    for label, _ in entries:
        if len(str(label)) > MAX_LABEL_LENGTH:
            raise ValueError(f"候选结构标签不得超过 {MAX_LABEL_LENGTH} 个字符")
    total_atoms = sum(len(structure) for _, structure in entries)
    if total_atoms > MAX_TOTAL_ATOMS:
        raise ValueError(f"预览总原子数不得超过 {MAX_TOTAL_ATOMS}")

    data = json.dumps(
        {"entries": [structure_payload(label, structure) for label, structure in entries]},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    if len(data.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise ValueError(f"viewer 页面数据不得超过 {MAX_SERIALIZED_BYTES} 字节")

    asset_root = _assets()
    metadata = renderer_metadata()
    renderer = asset_root.joinpath("3Dmol-min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    template = asset_root.joinpath("viewer.html").read_text(encoding="utf-8")
    license_text = html_module.escape(metadata["license_text"])
    page = template.replace("__RENDERER__", renderer).replace("__STRUCTURE_DATA__", data)
    page = page.replace("</footer>", "</footer><details><summary>第三方许可证</summary><pre>" + license_text + "</pre></details>")
    if len(page.encode("utf-8")) > MAX_SERIALIZED_BYTES + len(renderer.encode("utf-8")) + 32_768:
        raise ValueError("viewer 页面超出安全序列化限制")

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(page, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return ViewerArtifact(target, hashlib.sha256(target.read_bytes()).hexdigest())
