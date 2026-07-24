"""Minimal command-line entry point for the local generation pipeline."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-matgen")
    subparsers = parser.add_subparsers(dest="command")
    generate = subparsers.add_parser("generate", help="generate structures from a configured workflow")
    generate.add_argument("--config", help="path to a generation configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
