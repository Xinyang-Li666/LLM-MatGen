from pymatgen.core import Lattice, Structure


def rocksalt() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0, 0]]
    )


def fluorite() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.46), ["Ca", "F"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    )


def perovskite() -> Structure:
    return Structure.from_spacegroup(
        "Pm-3m",
        Lattice.cubic(3.905),
        ["Sr", "Ti", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0]],
    )


def spinel() -> Structure:
    return Structure.from_spacegroup(
        "Fd-3m",
        Lattice.cubic(8.08),
        ["Mg", "Al", "O"],
        [[0.5, 0.5, 0.5], [0.125, 0.125, 0.125], [0.3875, 0.3875, 0.3875]],
    )


def layered() -> Structure:
    return Structure(
        Lattice.hexagonal(2.46, 12.0),
        ["C", "C", "C", "C"],
        [[0, 0, 0.25], [1 / 3, 2 / 3, 0.25], [0, 0, 0.75], [2 / 3, 1 / 3, 0.75]],
    )


def test_deterministic_classifier_recognizes_five_supported_classes():
    from llm_matgen.sources.classifier import DeterministicStructureClassifier

    classifier = DeterministicStructureClassifier()
    for label, structure in {
        "layered": layered(),
        "perovskite": perovskite(),
        "spinel": spinel(),
        "rocksalt": rocksalt(),
        "fluorite": fluorite(),
    }.items():
        result = classifier.classify(structure, target=label)
        assert result.matched, (label, result)
        assert result.label == label
        assert result.method == "geometry-and-coordination"
        assert result.evidence


def test_classifier_returns_unknown_for_unsupported_or_invalid_structure():
    from llm_matgen.sources.classifier import DeterministicStructureClassifier

    result = DeterministicStructureClassifier().classify(
        Structure(Lattice.cubic(4), ["He"], [[0, 0, 0]])
    )
    assert result.label == "unknown"
    assert not result.matched
