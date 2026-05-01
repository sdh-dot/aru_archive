"""tools/repair_mojibake_via_v2.py 단위 테스트.

실제 v3 raw / v2 active 파일에 의존하지 않고, 합성 fixture로 검증.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "repair_mojibake_via_v2.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(
    input_path,
    reference_path,
    output_path,
    report_path,
    *,
    dry_run: bool = False,
    quiet: bool = True,
    expect_success: bool = True,
):
    cmd = [
        sys.executable,
        str(TOOL),
        str(input_path),
        "--reference", str(reference_path),
        "--output",    str(output_path),
        "--report",    str(report_path),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if quiet:
        cmd.append("--quiet")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"Tool failed (rc={result.returncode}):\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_raw(characters: list, *, series: list | None = None) -> dict:
    return {
        "pack_id":     "test_v3_raw",
        "name":        "Test V3 Raw",
        "version":     "1.0.0",
        "source":      "user_export",
        "exported_at": "2026-05-01T00:00:00Z",
        "series":      series or [],
        "characters":  characters,
    }


def _make_v2(characters: list, *, series: list | None = None) -> dict:
    return {
        "pack_id": "tag_pack_export",
        "name":    "Test V2",
        "version": "1.0.0",
        "source":  "failure_patched_v2_repaired",
        "series":  series or [],
        "characters": characters,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRepairMojibakeViaV2:

    def test_canonical_match_with_clean_v2_backfills_ko_and_ja(self, tmp_path):
        """A raw char with mojibake ko/ja that matches a clean v2 entry is repaired."""
        raw = _make_raw([
            {
                "canonical":    "Aru",
                "aliases":      ["Aru"],
                "parent_series": "Blue Archive",
                "localizations": {
                    "en": "Aru",
                    "ko": "??????",   # mojibake (6 ? = 100 %)
                    "ja": "?????",    # mojibake
                },
            }
        ])
        v2 = _make_v2([
            {
                "canonical":    "Aru",
                "aliases":      ["Aru"],
                "parent_series": "Blue Archive",
                "localizations": {
                    "en": "Aru",
                    "ko": "리쿠하치마 아루",
                    "ja": "陸八魔アル",
                },
            }
        ])
        raw_path  = tmp_path / "raw.json"
        v2_path   = tmp_path / "v2.json"
        out_path  = tmp_path / "out.json"
        rep_path  = tmp_path / "rep.json"
        _write_json(raw_path, raw)
        _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out  = _read_json(out_path)
        rep  = _read_json(rep_path)
        char = out["characters"][0]

        assert char["localizations"]["ko"] == "리쿠하치마 아루"
        assert char["localizations"]["ja"] == "陸八魔アル"
        assert rep["summary"]["ko_repaired"] == 1
        assert rep["summary"]["ja_repaired"] == 1
        assert rep["summary"]["ko_not_repaired"] == 0
        assert rep["summary"]["ja_not_repaired"] == 0

    def test_raw_normal_localization_is_not_overwritten(self, tmp_path):
        """A raw char whose ko/ja are already clean must not be changed."""
        raw = _make_raw([
            {
                "canonical":    "Aru",
                "aliases":      ["Aru"],
                "parent_series": "Blue Archive",
                "localizations": {
                    "en": "Aru",
                    "ko": "original-ko",
                    "ja": "original-ja",
                },
            }
        ])
        v2 = _make_v2([
            {
                "canonical":    "Aru",
                "aliases":      ["Aru"],
                "parent_series": "Blue Archive",
                "localizations": {"en": "Aru", "ko": "other-ko", "ja": "other-ja"},
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out  = _read_json(out_path)
        rep  = _read_json(rep_path)
        char = out["characters"][0]

        assert char["localizations"]["ko"] == "original-ko"
        assert char["localizations"]["ja"] == "original-ja"
        assert rep["summary"]["ko_repaired"] == 0
        assert rep["summary"]["ja_repaired"] == 0

    def test_v2_canonical_not_found_marks_review(self, tmp_path):
        """A raw char not present in v2 gets a _review marker."""
        raw = _make_raw([
            {
                "canonical":    "NewChar",
                "aliases":      ["NewChar"],
                "parent_series": "SomeSeries",
                "localizations": {"en": "NewChar", "ko": "???", "ja": "???"},
            }
        ])
        v2 = _make_v2([])  # empty reference
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out  = _read_json(out_path)
        rep  = _read_json(rep_path)
        char = out["characters"][0]

        assert "_review" in char
        review = char["_review"]
        assert review.get("needs_external_localization_source") is True
        assert "ko" in review.get("missing_locales", [])
        assert "ja" in review.get("missing_locales", [])
        assert review.get("repair_reason") == "v2_canonical_not_found"

        # Both locales not repaired
        assert rep["summary"]["ko_not_repaired"] == 1
        assert rep["summary"]["ja_not_repaired"] == 1

    def test_v2_value_mojibake_skips_repair(self, tmp_path):
        """If the v2 reference value is itself mojibake, skip repair."""
        raw = _make_raw([
            {
                "canonical":    "Char",
                "aliases":      ["Char"],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "???", "ja": "good-ja"},
            }
        ])
        v2 = _make_v2([
            {
                "canonical":    "Char",
                "aliases":      ["Char"],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "???"},  # v2 ko is also mojibake
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out = _read_json(out_path)
        rep = _read_json(rep_path)
        char = out["characters"][0]

        # ko not repaired (v2 also mojibake), ja was already good
        assert char["localizations"]["ko"] == "???"
        assert char["localizations"]["ja"] == "good-ja"
        assert rep["summary"]["ko_not_repaired"] == 1
        not_rep = rep["not_repaired_per_character"]
        assert any(
            e["canonical"] == "Char" and e["locale"] == "ko"
            and e["reason"] == "v2_value_mojibake"
            for e in not_rep
        )

    def test_v2_review_marker_skips_repair(self, tmp_path):
        """A v2 char flagged with _review must not be used as a repair source."""
        raw = _make_raw([
            {
                "canonical":    "Char",
                "aliases":      ["Char"],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "????", "ja": "????"},
            }
        ])
        v2 = _make_v2([
            {
                "canonical":    "Char",
                "aliases":      ["Char"],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "good-ko", "ja": "good-ja"},
                "_review": {"needs_localization_check": True},
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out = _read_json(out_path)
        rep = _read_json(rep_path)
        char = out["characters"][0]

        # Should NOT be repaired despite v2 having values
        assert "good" not in char["localizations"].get("ko", "")
        assert rep["summary"]["ko_not_repaired"] == 1
        not_rep = rep["not_repaired_per_character"]
        assert any(e["reason"] == "v2_review_marker" for e in not_rep)

    def test_alias_mojibake_is_not_modified(self, tmp_path):
        """Aliases containing mojibake must be preserved exactly as-is in output."""
        raw = _make_raw([
            {
                "canonical":    "Char",
                "aliases":      ["Char", "????"],  # alias with mojibake
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "good-ko", "ja": "good-ja"},
            }
        ])
        v2 = _make_v2([])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out = _read_json(out_path)
        rep = _read_json(rep_path)
        char = out["characters"][0]

        assert char["aliases"] == ["Char", "????"]
        assert rep["summary"]["alias_mojibake_found"] >= 1
        assert rep["summary"]["alias_repair_skipped"] >= 1

    def test_canonical_parent_series_aliases_unchanged(self, tmp_path):
        """canonical, parent_series, and aliases must not be altered."""
        raw = _make_raw([
            {
                "canonical":     "MyChar",
                "aliases":       ["MyChar", "mc"],
                "parent_series": "MySeries",
                "localizations": {"en": "MyChar", "ko": "???", "ja": "???"},
            }
        ])
        v2 = _make_v2([
            {
                "canonical":    "MyChar",
                "aliases":      ["MyChar", "mc"],
                "parent_series": "MySeries",
                "localizations": {"en": "MyChar", "ko": "마이캐릭", "ja": "マイキャラ"},
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out  = _read_json(out_path)
        char = out["characters"][0]

        assert char["canonical"]    == "MyChar"
        assert char["parent_series"] == "MySeries"
        assert char["aliases"]      == ["MyChar", "mc"]

    def test_output_preserves_top_level_keys_and_adds_lineage(self, tmp_path):
        """Output must carry original top-level keys plus lineage fields."""
        raw = _make_raw([], series=[{"canonical": "S", "aliases": []}])
        v2  = _make_v2([])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out = _read_json(out_path)

        # Original keys preserved
        for key in ("pack_id", "name", "version", "characters", "series"):
            assert key in out, f"Missing key: {key}"

        # Lineage fields added / overwritten
        assert out["source"] == "v3_draft_mojibake_repaired_via_v2"
        assert "repaired_at" in out
        assert "repaired_from" in out
        assert "repaired_with_reference" in out

    def test_report_summary_counts_correct(self, tmp_path):
        """Summary counts in the report must match the actual repairs."""
        raw = _make_raw([
            # will be repaired (ko + ja both mojibake, v2 clean)
            {
                "canonical":    "RepairMe",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "RepairMe", "ko": "????", "ja": "????"},
            },
            # not in v2 → not repaired
            {
                "canonical":    "NoV2",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "NoV2", "ko": "????", "ja": "????"},
            },
        ])
        v2 = _make_v2([
            {
                "canonical":    "RepairMe",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "RepairMe", "ko": "수리됨", "ja": "修理済"},
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        rep = _read_json(rep_path)
        s   = rep["summary"]

        assert s["total_characters"]  == 2
        assert s["ko_mojibake_found"] == 2
        assert s["ja_mojibake_found"] == 2
        assert s["ko_repaired"]       == 1
        assert s["ja_repaired"]       == 1
        assert s["ko_not_repaired"]   == 1
        assert s["ja_not_repaired"]   == 1

    def test_dry_run_does_not_write_output_or_report(self, tmp_path):
        """With --dry-run the output and report files must not be created."""
        raw = _make_raw([
            {
                "canonical":    "Char",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "???", "ja": "???"},
            }
        ])
        v2  = _make_v2([])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path, dry_run=True)

        assert not out_path.exists(), "Output file must not be written in dry-run mode"
        assert not rep_path.exists(), "Report file must not be written in dry-run mode"

    def test_invalid_input_path_returns_nonzero(self, tmp_path):
        """A non-existent input file must cause the tool to exit with non-zero."""
        v2_path  = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"
        rep_path = tmp_path / "rep.json"
        _write_json(v2_path, _make_v2([]))

        result = _run(
            tmp_path / "does_not_exist.json",
            v2_path,
            out_path,
            rep_path,
            expect_success=False,
        )
        assert result.returncode != 0

    def test_input_file_not_modified(self, tmp_path):
        """The input file must have the same SHA-256 before and after the run."""
        raw = _make_raw([
            {
                "canonical":    "Char",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "???", "ja": "???"},
            }
        ])
        v2 = _make_v2([
            {
                "canonical":    "Char",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "고쳐짐", "ja": "修正済"},
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        before = _sha256(raw_path)
        _run(raw_path, v2_path, out_path, rep_path)
        after  = _sha256(raw_path)

        assert before == after, "Input file was modified by the tool"

    def test_reference_file_not_modified(self, tmp_path):
        """The reference file must have the same SHA-256 before and after the run."""
        raw = _make_raw([])
        v2  = _make_v2([
            {
                "canonical":    "Char",
                "aliases":      [],
                "parent_series": "S",
                "localizations": {"en": "Char", "ko": "참조", "ja": "参照"},
            }
        ])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        before = _sha256(v2_path)
        _run(raw_path, v2_path, out_path, rep_path)
        after  = _sha256(v2_path)

        assert before == after, "Reference file was modified by the tool"

    def test_repaired_output_is_valid_json_with_required_keys(self, tmp_path):
        """The output file must be valid JSON with required top-level keys."""
        raw = _make_raw([])
        v2  = _make_v2([])
        raw_path = tmp_path / "raw.json"; v2_path = tmp_path / "v2.json"
        out_path = tmp_path / "out.json"; rep_path = tmp_path / "rep.json"
        _write_json(raw_path, raw); _write_json(v2_path, v2)

        _run(raw_path, v2_path, out_path, rep_path)

        out = _read_json(out_path)
        for key in ("pack_id", "name", "version", "source", "characters",
                    "repaired_at", "repaired_from", "repaired_with_reference"):
            assert key in out, f"Missing required key in output: {key}"
