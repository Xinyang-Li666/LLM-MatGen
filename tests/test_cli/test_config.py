import json
from pathlib import Path


def test_config_sets_only_non_sensitive_provider_and_model(tmp_path: Path, monkeypatch):
    from llm_matgen.__main__ import main

    config_path = tmp_path / "config.json"
    monkeypatch.setenv("LLM_MATGEN_CONFIG", str(config_path))
    assert main(["config", "set-provider", "openai-compatible"]) == 0
    assert main(["config", "set-model", "example-model"]) == 0
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "provider": "openai-compatible",
        "model": "example-model",
    }


def test_config_show_redacts_sensitive_environment(tmp_path: Path, monkeypatch, capsys):
    from llm_matgen.__main__ import main

    config_path = tmp_path / "config.json"
    config_path.write_text('{"provider":"local","model":"m"}', encoding="utf-8")
    monkeypatch.setenv("LLM_MATGEN_CONFIG", str(config_path))
    monkeypatch.setenv("MP_API_KEY", "super-secret")
    assert main(["config", "show"]) == 0
    output = capsys.readouterr().out
    assert "super-secret" not in output
    assert "***REDACTED***" in output


def test_config_set_key_is_explicitly_rejected(tmp_path: Path, monkeypatch, capsys):
    from llm_matgen.__main__ import main

    monkeypatch.setenv("LLM_MATGEN_CONFIG", str(tmp_path / "config.json"))
    assert main(["config", "set-key", "secret"]) == 2
    error = capsys.readouterr().err
    assert "environment variable" in error
    assert "keyring" in error
    assert "secret" not in error
