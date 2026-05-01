"""core.config_manager._DEFAULTS의 ui 섹션 회귀 가드."""
from __future__ import annotations


class TestConfigDefaults:
    def test_default_config_has_ui_section(self):
        from core.config_manager import _default_config
        cfg = _default_config()
        assert "ui" in cfg
        assert isinstance(cfg["ui"], dict)

    def test_startup_notice_seen_version_default_empty(self):
        from core.config_manager import _default_config
        cfg = _default_config()
        assert cfg["ui"].get("startup_notice_seen_version") == ""

    def test_existing_top_level_keys_preserved(self):
        """기존 top-level 키들이 깨지지 않았는지."""
        from core.config_manager import _default_config
        cfg = _default_config()
        for key in (
            "schema_version", "data_dir", "inbox_dir", "classified_dir",
            "managed_dir", "duplicates", "developer", "classification",
        ):
            assert key in cfg, f"기존 key {key!r}이 _default_config에서 누락됨"

    def test_load_config_creates_ui_section_for_legacy_config(self, tmp_path):
        """기존 config.json에 ui 섹션이 없어도 load_config가 default로 채움."""
        import json
        from core.config_manager import load_config
        legacy = tmp_path / "legacy_config.json"
        legacy.write_text(json.dumps({
            "schema_version": "1.0",
            "data_dir": "",
        }), encoding="utf-8")
        cfg = load_config(legacy)
        assert "ui" in cfg
        assert cfg["ui"].get("startup_notice_seen_version") == ""
