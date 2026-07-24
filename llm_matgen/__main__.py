"""Command-line entry point for LLM-MatGen."""

from __future__ import annotations

import argparse

EXIT_SUCCESS = 0
EXIT_PARAMETER = 2
EXIT_PARTIAL = 3
EXIT_SYSTEM = 4

GENERATOR_NAMES = (
    "vacancy",
    "interstitial",
    "doping",
    "solid-solution",
    "surface",
    "grain-boundary",
    "interface",
    "stacking-fault",
    "dislocation",
)


def _add_leaf(subparsers, name: str, help_text: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(_selected_parser=parser)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-matgen",
        description="Generate crystal structures with lightweight checks and reproducible manifests.",
    )
    commands = parser.add_subparsers(dest="command")
    _add_leaf(commands, "search", "search Materials Project structures")
    _add_leaf(commands, "download", "download Materials Project structures")
    _add_leaf(commands, "properties", "collect Materials Project properties")
    _add_leaf(commands, "substrates", "query substrate references")

    generate = _add_leaf(commands, "generate", "generate local crystal structures")
    generators = generate.add_subparsers(dest="generator")
    for name in GENERATOR_NAMES:
        _add_leaf(generators, name, f"generate {name} structures")

    _add_leaf(commands, "check", "run lightweight structure checks")
    _add_leaf(commands, "export", "convert structures to supported formats")
    _add_leaf(commands, "db", "manage local cache snapshots")
    _add_leaf(commands, "config", "manage non-sensitive configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected = getattr(args, "_selected_parser", parser)
    selected.print_help()
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
