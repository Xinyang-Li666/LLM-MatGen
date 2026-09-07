import json
from pathlib import Path

import pytest


def test_legacy_provider_model_config_remains_readable(tmp_path: Path):
    from llm_matgen.config import ConfigManager

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"provider": "deepseek", "model": "chat"}), encoding="utf-8")

    assert ConfigManager(path).load() == {"provider": "deepseek", "model": "chat"}


def test_nested_adsorption_configuration_is_typed(tmp_path: Path):
    from llm_matgen.adsorption.config import AdsorptionConfig, LocalSourceConfig
    from llm_matgen.config import ConfigManager

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "provider": "deepseek",
                "adsorption": {
                    "sources": [
                        {"type": "local", "name": "cases", "root": str(tmp_path / "cases")}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = ConfigManager(path).load_adsorption()
    assert isinstance(loaded, AdsorptionConfig)
    assert loaded.sources == (
        LocalSourceConfig(name="cases", root=tmp_path / "cases"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "http", "name": "cases", "root": "/tmp/cases"},
        {"type": "local", "name": "", "root": "/tmp/cases"},
        {"type": "ssh", "name": "cases", "host": "h", "root": "/data", "port": 0},
        {"type": "ssh", "name": "cases", "host": "h", "root": "/data", "port": 65536},
    ],
)
def test_invalid_source_configuration_is_rejected(payload):
    from llm_matgen.adsorption.config import AdsorptionConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdsorptionConfig(sources=[payload])


@pytest.mark.parametrize("field", ["password", "token", "secret", "api_key"])
def test_sensitive_fields_are_rejected_recursively(field):
    from llm_matgen.adsorption.config import AdsorptionConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdsorptionConfig(sources=[{"type": "local", "name": "cases", "root": "/tmp", field: "x"}])


def test_saving_adsorption_config_preserves_legacy_fields(tmp_path: Path):
    from llm_matgen.adsorption.config import AdsorptionConfig, LocalSourceConfig
    from llm_matgen.config import ConfigManager

    manager = ConfigManager(tmp_path / "config.json")
    manager.set("provider", "deepseek")
    manager.set_adsorption(
        AdsorptionConfig(
            sources=(LocalSourceConfig(name="cases", root=tmp_path / "cases"),)
        )
    )

    assert manager.load()["provider"] == "deepseek"
    assert manager.load_adsorption().sources[0].name == "cases"
