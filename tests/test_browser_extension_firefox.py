"""Firefox 확장 manifest 구조 및 filename fallback 동작 검증 테스트.

자동 검증 대상:
  1. aru-source-captioner-firefox/manifest.json — background.scripts, no service_worker, content_scripts.matches
  2. manifest.json — Chrome/Whale용 background.service_worker 존재 확인
  3. parsePixivFilenameUrl 동등 로직 — Python regex로 JS 동작 동일성 검증
  4. content.js — filename fallback 로그 문자열 삽입 확인
  5. content.js — safeJsonParse warn 로그 삽입 확인
  6. content.js — init() early return 제거 확인 (exifr 없어도 listener attach)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

EXT_DIR = Path(__file__).parent.parent / "browser-extension" / "aru-source-captioner"
EXT_DIR_FIREFOX = Path(__file__).parent.parent / "browser-extension" / "aru-source-captioner-firefox"
MANIFEST_CHROME = EXT_DIR / "manifest.json"
MANIFEST_FIREFOX = EXT_DIR_FIREFOX / "manifest.json"
CONTENT_JS = EXT_DIR / "content.js"


# ---------------------------------------------------------------------------
# 1. manifest_firefox.json 구조 검증
# ---------------------------------------------------------------------------

class TestFirefoxManifest:
    @pytest.fixture(autouse=True)
    def manifest(self):
        assert MANIFEST_FIREFOX.exists(), f"aru-source-captioner-firefox/manifest.json 없음: {MANIFEST_FIREFOX}"
        with open(MANIFEST_FIREFOX, encoding="utf-8") as f:
            self._data = json.load(f)

    @property
    def data(self):
        return self._data

    def test_background_scripts_present(self):
        """Firefox manifest에 background.scripts가 존재해야 한다."""
        bg = self.data.get("background", {})
        assert "scripts" in bg, f"background.scripts 없음: {bg}"
        assert isinstance(bg["scripts"], list) and len(bg["scripts"]) > 0

    def test_no_service_worker(self):
        """Firefox manifest에 background.service_worker가 없어야 한다."""
        bg = self.data.get("background", {})
        assert "service_worker" not in bg, (
            "Firefox manifest에 service_worker가 있으면 구형 Firefox(≤127)에서 background 실행 실패"
        )

    def test_content_scripts_matches_ruliweb(self):
        """content_scripts.matches에 bbs.ruliweb.com이 포함되어야 한다."""
        scripts = self.data.get("content_scripts", [])
        assert len(scripts) > 0, "content_scripts 없음"
        matches = scripts[0].get("matches", [])
        ruliweb = [m for m in matches if "bbs.ruliweb.com" in m]
        assert ruliweb, f"bbs.ruliweb.com 미포함: {matches}"

    def test_content_scripts_includes_write_page(self):
        """board/300143/* 패턴이 있어야 글쓰기 페이지에서 content script가 실행된다."""
        scripts = self.data.get("content_scripts", [])
        matches = scripts[0].get("matches", [])
        board_300143 = [m for m in matches if "board/300143" in m]
        assert board_300143, f"board/300143 패턴 없음: {matches}"

    def test_content_scripts_includes_read_page(self):
        """board/*/read/* 패턴이 있어야 댓글(read) 페이지에서 content script가 실행된다."""
        scripts = self.data.get("content_scripts", [])
        matches = scripts[0].get("matches", [])
        read_page = [m for m in matches if "/read/" in m]
        assert read_page, f"/read/ 패턴 없음: {matches}"

    def test_content_scripts_js_order(self):
        """exifr.full.umd.js가 content.js보다 먼저 로드되어야 한다."""
        scripts = self.data.get("content_scripts", [])
        js_list = scripts[0].get("js", [])
        assert any("exifr" in s for s in js_list), "exifr.full.umd.js 없음"
        assert "content.js" in js_list, "content.js 없음"
        exifr_idx = next(i for i, s in enumerate(js_list) if "exifr" in s)
        content_idx = js_list.index("content.js")
        assert exifr_idx < content_idx, "exifr가 content.js보다 뒤에 로드됨"

    def test_permissions_storage(self):
        """storage 권한이 있어야 chrome.storage.sync를 사용할 수 있다."""
        perms = self.data.get("permissions", [])
        assert "storage" in perms


# ---------------------------------------------------------------------------
# 2. manifest.json (Chrome용) 구조 검증
# ---------------------------------------------------------------------------

class TestChromeManifest:
    @pytest.fixture(autouse=True)
    def manifest(self):
        assert MANIFEST_CHROME.exists(), f"manifest.json 없음: {MANIFEST_CHROME}"
        with open(MANIFEST_CHROME, encoding="utf-8") as f:
            self._data = json.load(f)

    @property
    def data(self):
        return self._data

    def test_service_worker_present(self):
        """Chrome manifest에는 background.service_worker가 있어야 한다."""
        bg = self.data.get("background", {})
        assert "service_worker" in bg, f"Chrome manifest에 service_worker 없음: {bg}"


# ---------------------------------------------------------------------------
# 3. parsePixivFilenameUrl 동등 로직 — Python으로 JS regex 동일성 검증
# ---------------------------------------------------------------------------

# JS: /^(\d{6,12})_p\d+(?:_|\.|$)/   +   /^(\d{6,12})\.(jpg|jpeg|png|webp)$/i
_PIXIV_PATTERN_1 = re.compile(r'^(\d{6,12})_p\d+(?:_|\.|$)')
_PIXIV_PATTERN_2 = re.compile(r'^(\d{6,12})\.(jpg|jpeg|png|webp)$', re.IGNORECASE)

def parse_pixiv_filename_url(filename: str) -> str | None:
    m = _PIXIV_PATTERN_1.match(filename)
    if m:
        return f"https://www.pixiv.net/artworks/{m.group(1)}"
    m2 = _PIXIV_PATTERN_2.match(filename)
    if m2:
        return f"https://www.pixiv.net/artworks/{m2.group(1)}"
    return None


class TestParsePixivFilenameUrl:
    @pytest.mark.parametrize("filename,expected_id", [
        ("88908024_p0_master1200.jpg",   "88908024"),
        ("78563767_p5_master1200.webp",  "78563767"),
        ("72043386_p0.jpg",              "72043386"),
        ("72043386_p0.png",              "72043386"),
        ("88908024_p0.webp",             "88908024"),
        ("123456_p0_master1200.jpg",     "123456"),
        ("123456789012_p0.jpg",          "123456789012"),
    ])
    def test_pixiv_pattern_matches(self, filename, expected_id):
        """Pixiv 표준 파일명에서 올바른 artwork_id를 추출한다."""
        url = parse_pixiv_filename_url(filename)
        assert url == f"https://www.pixiv.net/artworks/{expected_id}", (
            f"{filename} → {url}"
        )

    @pytest.mark.parametrize("filename", [
        "sample_photo.jpg",
        "12345.jpg",           # 5자리 이하 — 오탐 방지
        "12345_p0.jpg",        # 5자리 이하
        "screenshot.png",
        "89b60d43b5d23e86.jpg",  # hash 파일명 (Aru hash)
        "1234567890123_p0.jpg",  # 13자리 — 범위 초과
        "noext_88908024_p0",   # prefix가 있는 경우 — 시작 앵커로 불매칭
    ])
    def test_non_pixiv_filename_returns_none(self, filename):
        """Pixiv 패턴이 아닌 파일명은 None을 반환한다."""
        assert parse_pixiv_filename_url(filename) is None, (
            f"{filename}이 잘못 매칭됨"
        )

    def test_webp_fallback_from_filename(self):
        """WebP 파일도 파일명에서 Pixiv URL을 추출할 수 있다."""
        url = parse_pixiv_filename_url("78563767_p5_master1200.webp")
        assert url == "https://www.pixiv.net/artworks/78563767"

    def test_malformed_json_still_reaches_filename_fallback(self):
        """malformed JSON은 None을 반환하고 filename fallback으로 이어져야 한다."""
        # safeJsonParse 동등 로직
        def safe_json_parse(text: str):
            if not isinstance(text, str):
                return None
            t = text.strip()
            if not (t.startswith("{") or t.startswith("[")):
                return None
            try:
                return json.loads(t)
            except json.JSONDecodeError:
                return None

        malformed_inputs = [
            "{'artwork_id': '88908024'}",   # single quote
            '{artwork_id: "88908024"}',      # unquoted key
            '{"artwork_id": "88908024",}',  # trailing comma
            "UNICODE\x00garbage",            # UTF-16LE 잔재
            "",
        ]
        for text in malformed_inputs:
            result = safe_json_parse(text)
            assert result is None, f"malformed JSON이 성공 반환됨: {text!r}"

        # JSON 실패 후 filename fallback 경로가 살아있어야 함
        url = parse_pixiv_filename_url("88908024_p0_master1200.jpg")
        assert url == "https://www.pixiv.net/artworks/88908024"


# ---------------------------------------------------------------------------
# 4. content.js 소스 패치 검증 — 로그 문자열 및 guard 삽입 여부
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def content_js_text():
    assert CONTENT_JS.exists(), f"content.js 없음: {CONTENT_JS}"
    return CONTENT_JS.read_text(encoding="utf-8")


class TestContentJsPatchVerification:
    def test_init_startup_log_present(self, content_js_text):
        """init() 상단에 content loaded 로그가 있어야 한다 (Firefox Browser Console 확인용)."""
        assert "[Aru Source Captioner] content loaded" in content_js_text

    def test_exifr_unavailable_no_early_return(self, content_js_text):
        """exifr 없는 경우 early return으로 attachFileInputListeners를 건너뛰지 않아야 한다."""
        # 수정 전 패턴: exifr undefined → return (이후 attachFileInputListeners 없음)
        # 수정 후: warn 로그만 출력하고 attachFileInputListeners를 호출
        bad_pattern = re.compile(
            r'typeof exifr\s*===\s*["\']undefined["\'][\s\S]{0,200}?return;',
            re.MULTILINE
        )
        # early return이 있더라도 그 이후에 attachFileInputListeners 호출이 있으면 OK
        # → bad_pattern 매칭 없어야 한다
        assert not bad_pattern.search(content_js_text), (
            "exifr undefined 체크 후 early return이 있어 attachFileInputListeners가 호출되지 않음"
        )

    def test_filename_fallback_log_in_all_paths(self, content_js_text):
        """parseSourceFromFile 내 filename fallback 4곳 모두에 info 로그가 있어야 한다."""
        # "filename fallback" 로그가 content.js에 4번 이상 있어야 한다
        count = content_js_text.count('"[Aru Source Captioner] filename fallback"')
        assert count >= 4, f"filename fallback 로그가 {count}개뿐 (4개 이상 필요)"

    def test_safe_json_parse_has_warn_log(self, content_js_text):
        """safeJsonParse 실패 시 non-fatal warn 로그가 있어야 한다."""
        assert "JSON parse failed; fallback continues" in content_js_text

    def test_exifr_filename_only_mode_log(self, content_js_text):
        """exifr 없을 때 filename-only 모드 경고 로그가 있어야 한다."""
        assert "filename-only fallback mode" in content_js_text

    def test_no_inner_html_usage(self, content_js_text):
        """innerHTML이 실제 코드(비주석)에서 사용되지 않아야 한다 (XSS 방지)."""
        for line in content_js_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            assert "innerHTML" not in stripped, f"innerHTML 코드 사용 발견: {stripped}"

    def test_no_eval_usage(self, content_js_text):
        """eval() 사용 금지."""
        assert "eval(" not in content_js_text


# ---------------------------------------------------------------------------
# 5. WebP filename fallback — 특이 케이스
# ---------------------------------------------------------------------------

class TestWebpFilenameFallback:
    def test_webp_with_pixiv_pattern(self):
        """WebP exifr 실패 후에도 filename fallback으로 Pixiv URL이 생성된다."""
        url = parse_pixiv_filename_url("78563767_p5_master1200.webp")
        assert url == "https://www.pixiv.net/artworks/78563767"

    def test_webp_without_pixiv_pattern(self):
        """Pixiv 파일명이 아닌 WebP는 None이 반환된다."""
        assert parse_pixiv_filename_url("image_sample.webp") is None

    def test_webp_no_exif_still_filename_fallback(self, content_js_text):
        """WebP missing 분기 이전에 filename fallback이 먼저 시도되어야 한다."""
        # parseSourceFromFile 내에서 isWebp check 전에 filenameUrl 시도가 있어야 함.
        # "webp_no_exif" 앞에 "filename_fallback" 이 동일 catch block에 있는지 확인.
        # exifr catch block을 찾아 순서 검증.
        catch_block_start = content_js_text.find("exifr.parse failed")
        assert catch_block_start != -1, "exifr.parse failed 로그 없음"
        # catch block 내에서 filename fallback이 webp_no_exif보다 앞에 있어야 함
        segment = content_js_text[catch_block_start:catch_block_start + 600]
        fb_pos = segment.find("filename_fallback")
        webp_pos = segment.find("webp_no_exif")
        assert fb_pos != -1, "catch block 내 filename_fallback 없음"
        assert webp_pos != -1, "catch block 내 webp_no_exif 없음"
        assert fb_pos < webp_pos, (
            "filename fallback 시도가 webp_no_exif return 이후에 있음 — 순서가 잘못됨"
        )
