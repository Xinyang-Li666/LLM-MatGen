from llm_matgen.__main__ import build_parser


def test_cli_help_parser_has_generate_command():
    parser = build_parser()
    assert "generate" in parser._subparsers._group_actions[0].choices
