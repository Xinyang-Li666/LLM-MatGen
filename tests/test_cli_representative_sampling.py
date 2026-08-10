from __future__ import annotations

from llm_matgen.__main__ import build_parser


def test_representative_cli_accepts_source_config_and_options():
    parser = build_parser()
    args = parser.parse_args([
        "sample", "representative", "--source-config", "sources.json", "--method", "rdf-fps",
        "--count", "10", "--allocation", "proportional", "--min-distance", "0.2",
    ])
    assert args.method == "rdf-fps"
    assert args.count == 10


def test_representative_cli_requires_exactly_one_input_mode():
    parser = build_parser()
    args = parser.parse_args(["sample", "representative", "--method", "rdf-fps", "--count", "2"])
    assert args.input is None and args.source_config is None


def test_representative_cli_exposes_soap_backend_options():
    args = build_parser().parse_args([
        "sample", "representative", "trajectory.extxyz", "--method", "soap-fps", "--count", "3",
        "--soap-r-cut", "4.0", "--soap-n-max", "2", "--soap-l-max", "2",
    ])
    assert args.method == "soap-fps" and args.soap_n_max == 2
