import pytest


def test_cli_exposes_documented_top_level_commands():
    from llm_matgen.__main__ import build_parser

    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert set(choices) == {
        "search", "download", "properties", "substrates", "generate",
        "check", "export", "convert", "sample", "filter", "db", "mcp", "config", "cases", "revision",
    }


def test_mcp_help_is_available_without_starting_server(capsys):
    from llm_matgen.__main__ import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["mcp", "--help"])
    assert caught.value.code == 0
    assert "output-root" in capsys.readouterr().out


def test_lammps_mapping_help_documents_atomic_number_fallback(capsys):
    from llm_matgen.__main__ import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["check", "--help"])
    assert caught.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "default to" in output
    assert "atomic numbers" in output


def test_generate_help_exposes_all_ten_generators(capsys):
    from llm_matgen.__main__ import build_parser

    parser = build_parser()
    generate = parser._subparsers._group_actions[0].choices["generate"]
    choices = generate._subparsers._group_actions[0].choices
    assert set(choices) == {
        "vacancy", "interstitial", "doping", "solid-solution", "surface",
        "grain-boundary", "interface", "stacking-fault", "dislocation", "adsorption",
    }
    for command in choices:
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(["generate", command, "--help"])
        assert caught.value.code == 0


def test_cli_exit_codes_are_stable():
    from llm_matgen.__main__ import EXIT_PARAMETER, EXIT_PARTIAL, EXIT_SUCCESS, EXIT_SYSTEM

    assert (EXIT_SUCCESS, EXIT_PARAMETER, EXIT_PARTIAL, EXIT_SYSTEM) == (0, 2, 3, 4)
