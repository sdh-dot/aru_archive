"""classification_level config default 회귀 가드."""
from __future__ import annotations

import json
import pytest


class TestClassificationLevelDefault:
    def test_default_config_has_classification_level(self):
        from core.config_manager import _default_config
        cfg = _default_config()
        assert "classification" in cfg
        assert cfg["classification"].get("classification_level") == "series_character"

    def test_legacy_config_without_classification_key_gets_default_level(self, tmp_path):
        """classification 키 자체가 없는 legacy 파일 → _default_config() 값이 그대로 유지."""
        from core.config_manager import load_config
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"data_dir": "/some/path"}), encoding="utf-8")
        cfg = load_config(legacy)
        # classification 키가 없을 때는 _default_config()의 값이 유지된다
        assert cfg["classification"].get("classification_level") == "series_character"

    def test_explicit_series_only_preserved(self, tmp_path):
        from core.config_manager import load_config
        explicit = tmp_path / "cfg_series_only.json"
        explicit.write_text(
            json.dumps({"classification": {"classification_level": "series_only"}}),
            encoding="utf-8",
        )
        cfg = load_config(explicit)
        assert cfg["classification"].get("classification_level") == "series_only"
