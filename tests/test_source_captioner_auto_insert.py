"""Source Captioner 자동 출처 삽입 전환 검증 테스트.

검증 범위:
  1. Firefox manifest — gecko / gecko_android 설정
  2. Chromium manifest — gecko_android 미포함
  3. Firefox content.js — isMobileAutoInsertEnvironment 존재
  4. Firefox content.js — processedFileKeys / makeFileKey 중복 방지 존재
  5. Firefox content.js — 자동 삽입 모드 (버튼 주입 기본 비활성화)
  6. Firefox content.js — hookCommentFileInput 자동 삽입 경로 유지
  7. Firefox content.js — filename fallback 유지
  8. Firefox content.js — setupCommentSourceCaptioner에서 injectCommentSourceButton 미호출
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
CONTENT_JS_FIREFOX = EXT_DIR_FIREFOX / "content.js"


@pytest.fixture(scope="module")
def ff_manifest() -> dict:
    assert MANIFEST_FIREFOX.exists(), f"Firefox manifest 없음: {MANIFEST_FIREFOX}"
    with open(MANIFEST_FIREFOX, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def chrome_manifest() -> dict:
    assert MANIFEST_CHROME.exists(), f"Chrome manifest 없음: {MANIFEST_CHROME}"
    with open(MANIFEST_CHROME, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ff_content_js() -> str:
    assert CONTENT_JS_FIREFOX.exists(), f"Firefox content.js 없음: {CONTENT_JS_FIREFOX}"
    return CONTENT_JS_FIREFOX.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Firefox manifest — gecko / gecko_android 설정
# ---------------------------------------------------------------------------

class TestFirefoxAndroidManifest:

    def test_browser_specific_settings_present(self, ff_manifest):
        assert "browser_specific_settings" in ff_manifest, (
            "browser_specific_settings 없음"
        )

    def test_gecko_id(self, ff_manifest):
        bss = ff_manifest["browser_specific_settings"]
        gecko = bss.get("gecko", {})
        assert gecko.get("id") == "aru-source-captioner@sdh-dot.github.io"

    def test_gecko_strict_min_version(self, ff_manifest):
        bss = ff_manifest["browser_specific_settings"]
        gecko = bss.get("gecko", {})
        assert gecko.get("strict_min_version") == "140.0"

    def test_data_collection_permissions_required_none(self, ff_manifest):
        bss = ff_manifest["browser_specific_settings"]
        gecko = bss.get("gecko", {})
        dcp = gecko.get("data_collection_permissions", {})
        assert dcp.get("required") == ["none"], (
            f"data_collection_permissions.required 오류: {dcp}"
        )

    def test_gecko_android_present(self, ff_manifest):
        bss = ff_manifest["browser_specific_settings"]
        assert "gecko_android" in bss, "gecko_android 없음"

    def test_gecko_android_strict_min_version(self, ff_manifest):
        bss = ff_manifest["browser_specific_settings"]
        ga = bss.get("gecko_android", {})
        assert ga.get("strict_min_version") == "142.0", (
            f"gecko_android.strict_min_version 오류: {ga}"
        )

    def test_background_scripts_preserved(self, ff_manifest):
        bg = ff_manifest.get("background", {})
        assert "scripts" in bg, "background.scripts 없음"
        assert isinstance(bg["scripts"], list) and len(bg["scripts"]) > 0

    def test_no_service_worker(self, ff_manifest):
        bg = ff_manifest.get("background", {})
        assert "service_worker" not in bg, (
            "Firefox manifest에 service_worker가 있으면 안 됨"
        )


# ---------------------------------------------------------------------------
# 2. Chromium/Whale manifest — gecko_android 미포함
# ---------------------------------------------------------------------------

class TestChromeManifestNoGecko:

    def test_no_browser_specific_settings(self, chrome_manifest):
        assert "browser_specific_settings" not in chrome_manifest, (
            "Chromium manifest에 browser_specific_settings가 있으면 안 됨"
        )

    def test_no_gecko_android(self, chrome_manifest):
        bss = chrome_manifest.get("browser_specific_settings", {})
        assert "gecko_android" not in bss

    def test_service_worker_present(self, chrome_manifest):
        """Chromium manifest에는 service_worker가 있어야 한다."""
        bg = chrome_manifest.get("background", {})
        assert "service_worker" in bg


# ---------------------------------------------------------------------------
# 3. Firefox content.js — isMobileAutoInsertEnvironment
# ---------------------------------------------------------------------------

class TestMobileAutoInsertHelper:

    def test_helper_function_defined(self, ff_content_js):
        assert "isMobileAutoInsertEnvironment" in ff_content_js, (
            "isMobileAutoInsertEnvironment 함수가 없음"
        )

    def test_android_ua_detection(self, ff_content_js):
        """Android UA 탐지 로직이 있어야 한다."""
        assert "/Android/i" in ff_content_js or '"Android"' in ff_content_js or "Android" in ff_content_js

    def test_coarse_pointer_check(self, ff_content_js):
        """pointer: coarse 체크가 있어야 한다."""
        assert "pointer: coarse" in ff_content_js

    def test_helper_returns_boolean(self, ff_content_js):
        """함수가 boolean(true/false)을 반환해야 한다."""
        # isMobileAutoInsertEnvironment 함수 내에 return true / return false 가 있어야 함
        assert "return true" in ff_content_js
        assert "return false" in ff_content_js

    def test_helper_has_try_catch_guard(self, ff_content_js):
        """isMobileAutoInsertEnvironment 내부에 try/catch로 예외를 방어해야 한다."""
        # 함수 정의에서 600자 이내에 try + catch 쌍이 있어야 함 (함수 본문이 ~400자)
        pattern = re.compile(
            r"function isMobileAutoInsertEnvironment\(\)[\s\S]{0,600}?catch",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "isMobileAutoInsertEnvironment에 try/catch 방어가 없음"
        )


# ---------------------------------------------------------------------------
# 4. Firefox content.js — processedFileKeys / makeFileKey 중복 방지
# ---------------------------------------------------------------------------

class TestDuplicateFilePrevention:

    def test_processed_file_keys_set_defined(self, ff_content_js):
        assert "processedFileKeys" in ff_content_js, (
            "processedFileKeys Set이 없음"
        )

    def test_make_file_key_defined(self, ff_content_js):
        assert "makeFileKey" in ff_content_js, (
            "makeFileKey 함수가 없음"
        )

    def test_file_key_uses_name_size_lastmodified(self, ff_content_js):
        """makeFileKey가 name, size, lastModified를 모두 조합해야 한다."""
        pattern = re.compile(
            r"function makeFileKey\(file\)[\s\S]{0,200}?file\.name[\s\S]{0,100}?file\.size[\s\S]{0,100}?file\.lastModified",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "makeFileKey가 name|size|lastModified 조합을 사용하지 않음"
        )

    def test_processed_keys_checked_before_processing(self, ff_content_js):
        """handleSelectedImageFiles에서 processedFileKeys.has() 체크가 있어야 한다."""
        assert "processedFileKeys.has(" in ff_content_js

    def test_processed_keys_added_after_check(self, ff_content_js):
        """처리 후 processedFileKeys.add()로 등록해야 한다."""
        assert "processedFileKeys.add(" in ff_content_js

    def test_skip_log_for_duplicate(self, ff_content_js):
        """중복 파일 건너뛰기 로그가 있어야 한다."""
        assert "already-processed file" in ff_content_js or "skipping" in ff_content_js


# ---------------------------------------------------------------------------
# 5. Firefox content.js — 자동 삽입 모드 (버튼 주입 기본 비활성화)
# ---------------------------------------------------------------------------

class TestAutoInsertMode:

    def test_inject_button_function_still_defined(self, ff_content_js):
        """injectCommentSourceButton 함수 정의는 유지된다 (debug용)."""
        assert "function injectCommentSourceButton(" in ff_content_js

    def test_setup_does_not_call_inject_button(self, ff_content_js):
        """setupCommentSourceCaptioner 본문에서 injectCommentSourceButton을 호출하지 않아야 한다."""
        # setupCommentSourceCaptioner 함수 본문 추출
        pattern = re.compile(
            r"function setupCommentSourceCaptioner\(config\)\s*\{([\s\S]*?)(?=\n  (?:let|const|function|var)\s|\n  [a-zA-Z]+Observer|\Z)",
            re.MULTILINE
        )
        m = pattern.search(ff_content_js)
        if m:
            body = m.group(1)
            # 함수 본문 내에서 injectCommentSourceButton( 호출이 없어야 함
            assert "injectCommentSourceButton(" not in body, (
                "setupCommentSourceCaptioner가 injectCommentSourceButton을 호출하고 있음"
            )
        else:
            # 본문 추출 실패 시 전체에서 setupCommentSourceCaptioner 블록만 검사
            idx = ff_content_js.find("function setupCommentSourceCaptioner(")
            assert idx != -1, "setupCommentSourceCaptioner 함수를 찾을 수 없음"
            segment = ff_content_js[idx:idx + 800]
            assert "injectCommentSourceButton(" not in segment, (
                "setupCommentSourceCaptioner 첫 800자 내에 injectCommentSourceButton 호출이 있음"
            )

    def test_auto_insert_mode_log(self, ff_content_js):
        """자동 삽입 모드 관련 로그가 있어야 한다."""
        assert "auto-insert mode" in ff_content_js

    def test_mobile_flag_in_init_log(self, ff_content_js):
        """init 로그에 mobile 키가 포함되어야 한다."""
        assert "mobile: isMobileAutoInsertEnvironment()" in ff_content_js


# ---------------------------------------------------------------------------
# 6. Firefox content.js — hookCommentFileInput 자동 삽입 경로 유지
# ---------------------------------------------------------------------------

class TestAutoInsertPath:

    def test_hook_comment_file_input_defined(self, ff_content_js):
        assert "function hookCommentFileInput(" in ff_content_js

    def test_auto_insert_into_textarea(self, ff_content_js):
        """hookCommentFileInput에서 insertSourceIntoCommentTextarea를 호출해야 한다."""
        assert "insertSourceIntoCommentTextarea(" in ff_content_js

    def test_wrapper_source_map_used(self, ff_content_js):
        """wrapperSourceMap에 source를 저장해야 한다."""
        assert "wrapperSourceMap.set(" in ff_content_js

    def test_no_external_request(self, ff_content_js):
        """fetch / XMLHttpRequest 등 외부 요청이 없어야 한다."""
        assert "fetch(" not in ff_content_js
        assert "XMLHttpRequest" not in ff_content_js


# ---------------------------------------------------------------------------
# 7. Firefox content.js — filename fallback 유지
# ---------------------------------------------------------------------------

class TestFilenameFallbackPreserved:

    def test_parse_pixiv_filename_url_defined(self, ff_content_js):
        assert "parsePixivFilenameUrl" in ff_content_js

    def test_filename_fallback_log_present(self, ff_content_js):
        """filename fallback 경로에 로그가 있어야 한다 (4곳 이상)."""
        count = ff_content_js.count('"[Aru Source Captioner] filename fallback"')
        assert count >= 4, f"filename fallback 로그가 {count}개뿐 (4개 이상 필요)"

    def test_filename_only_mode_warning(self, ff_content_js):
        """exifr 없을 때 filename-only 모드 경고가 있어야 한다."""
        assert "filename-only fallback mode" in ff_content_js

    def test_no_early_return_blocking_filename_fallback(self, ff_content_js):
        """exifr undefined 체크 후 early return이 attachFileInputListeners를 건너뛰면 안 된다."""
        bad_pattern = re.compile(
            r'typeof exifr\s*===\s*["\']undefined["\'][\s\S]{0,200}?return;',
            re.MULTILINE
        )
        assert not bad_pattern.search(ff_content_js), (
            "exifr undefined 체크 후 early return이 있어 filename fallback이 막힘"
        )


# ---------------------------------------------------------------------------
# 8. Firefox content.js — XSS / 보안 정책
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 9. Firefox content.js — 모바일 글쓰기 직접 삽입
# ---------------------------------------------------------------------------

class TestMobileWriteInsert:

    def test_find_mobile_write_area_defined(self, ff_content_js):
        assert "findMobileWriteArea" in ff_content_js

    def test_try_mobile_write_insert_defined(self, ff_content_js):
        assert "tryMobileWriteInsert" in ff_content_js

    def test_write_textarea_exclude_pattern_defined(self, ff_content_js):
        """댓글/답글 textarea를 제외하는 패턴이 있어야 한다."""
        assert "WRITE_TEXTAREA_EXCLUDE_PATTERN" in ff_content_js

    def test_cached_config_defined(self, ff_content_js):
        """cachedConfig 모듈 변수가 정의되어 있어야 한다."""
        assert "cachedConfig" in ff_content_js

    def test_mobile_write_insert_called_on_file_select(self, ff_content_js):
        """handleSelectedImageFiles에서 모바일 조건 하에 tryMobileWriteInsert를 호출해야 한다."""
        assert "tryMobileWriteInsert(" in ff_content_js
        assert "isMobileAutoInsertEnvironment()" in ff_content_js
        assert "!isReadPage()" in ff_content_js

    def test_mobile_insert_uses_sanitize_url(self, ff_content_js):
        """tryMobileWriteInsert 내부에서 sanitizeSourceUrl을 호출해야 한다."""
        pattern = re.compile(
            r"function tryMobileWriteInsert\([\s\S]{0,600}?sanitizeSourceUrl",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "tryMobileWriteInsert에서 sanitizeSourceUrl 호출 없음"
        )

    def test_mobile_insert_no_op_when_no_target(self, ff_content_js):
        """write area를 찾지 못하면 warn만 남기고 no-op 해야 한다."""
        assert "no write area found" in ff_content_js or "no-op" in ff_content_js

    def test_mobile_insert_textarea_path_reuses_insert_function(self, ff_content_js):
        """textarea인 경우 insertSourceIntoCommentTextarea를 재사용해야 한다."""
        pattern = re.compile(
            r"function tryMobileWriteInsert\([\s\S]{0,800}?insertSourceIntoCommentTextarea",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "tryMobileWriteInsert에서 insertSourceIntoCommentTextarea 재사용 없음"
        )

    def test_mobile_insert_contenteditable_duplicate_guard(self, ff_content_js):
        """contenteditable 경로에서 이미 URL이 있으면 skip 해야 한다."""
        assert "already in editor" in ff_content_js or "caption already" in ff_content_js


# ---------------------------------------------------------------------------
# 10. 보안 정책
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 11. 모바일(m.ruliweb.com) content script 주입 커버리지
# ---------------------------------------------------------------------------

class TestMobileManifestCoverage:

    def test_mobile_write_page_in_matches(self, ff_manifest):
        """m.ruliweb.com 글쓰기 URL이 content_scripts.matches에 있어야 한다."""
        scripts = ff_manifest.get("content_scripts", [])
        assert scripts, "content_scripts 없음"
        matches = scripts[0].get("matches", [])
        mobile_write = [m for m in matches if "m.ruliweb.com" in m and "300143" in m]
        assert mobile_write, (
            f"m.ruliweb.com board/300143 패턴 없음: {matches}\n"
            "→ m.ruliweb.com/community/board/300143/write 에서 content script 미주입"
        )

    def test_mobile_read_page_in_matches(self, ff_manifest):
        """m.ruliweb.com 댓글 페이지가 content_scripts.matches에 있어야 한다."""
        scripts = ff_manifest.get("content_scripts", [])
        matches = scripts[0].get("matches", [])
        mobile_read = [m for m in matches if "m.ruliweb.com" in m and "/read/" in m]
        assert mobile_read, f"m.ruliweb.com /read/ 패턴 없음: {matches}"

    def test_mobile_in_host_permissions(self, ff_manifest):
        """host_permissions에 m.ruliweb.com 항목이 있어야 한다."""
        hp = ff_manifest.get("host_permissions", [])
        mobile_hp = [h for h in hp if "m.ruliweb.com" in h]
        assert mobile_hp, f"host_permissions에 m.ruliweb.com 없음: {hp}"

    def test_desktop_matches_not_removed(self, ff_manifest):
        """모바일 추가 후 기존 bbs.ruliweb.com matches가 유지되어야 한다."""
        scripts = ff_manifest.get("content_scripts", [])
        matches = scripts[0].get("matches", [])
        bbs = [m for m in matches if "bbs.ruliweb.com" in m]
        assert len(bbs) >= 2, f"bbs.ruliweb.com 패턴 누락 — 데스크톱 동작 깨짐: {matches}"

    def test_sync_boot_log_present(self, ff_content_js):
        """동기 boot 로그가 있어야 content script 주입 여부를 즉시 확인할 수 있다."""
        assert "content script loaded" in ff_content_js, (
            "[Aru Source Captioner] content script loaded 동기 로그 없음 — "
            "주입 여부를 async init() 전에 확인할 수 없음"
        )


# ---------------------------------------------------------------------------
# 12. 중복 삽입 방지 (mobile double-insert hotfix)
# ---------------------------------------------------------------------------

class TestDuplicateInsertPrevention:

    def test_pending_file_keys_set_defined(self, ff_content_js):
        """pendingFileKeys Set이 정의되어 있어야 한다 (비동기 경합 방지)."""
        assert "pendingFileKeys" in ff_content_js

    def test_handled_file_events_weakset_defined(self, ff_content_js):
        """handledFileEvents WeakSet이 정의되어 있어야 한다 (이벤트 중복 실행 방지)."""
        assert "handledFileEvents" in ff_content_js

    def test_event_guard_in_attach_listener(self, ff_content_js):
        """attachFileInputListeners에서 handledFileEvents.has(ev) 가드가 있어야 한다."""
        assert "handledFileEvents.has(ev)" in ff_content_js
        assert "handledFileEvents.add(ev)" in ff_content_js

    def test_pending_key_guard_in_handle_files(self, ff_content_js):
        """handleSelectedImageFiles에서 pendingFileKeys.has(key) 가드가 있어야 한다."""
        assert "pendingFileKeys.has(key)" in ff_content_js

    def test_pending_key_lifecycle_add_and_finally_delete(self, ff_content_js):
        """pendingFileKeys는 추가(add)되고 finally에서 반드시 삭제(delete)되어야 한다."""
        assert "pendingFileKeys.add(key)" in ff_content_js
        assert "pendingFileKeys.delete(key)" in ff_content_js

    def test_mobile_insert_result_consumed_on_success(self, ff_content_js):
        """모바일 insert 성공 시 pending record를 소비해 observer 중복 삽입을 막아야 한다."""
        pattern = re.compile(
            r"const inserted = tryMobileWriteInsert\([\s\S]{0,200}?if \(inserted\)[\s\S]{0,100}?consumePendingRecordByFileName",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "tryMobileWriteInsert 결과를 받아 inserted=true일 때 consumePendingRecordByFileName을 호출하지 않음"
        )

    def test_try_mobile_write_insert_returns_true_on_contenteditable(self, ff_content_js):
        """tryMobileWriteInsert가 contenteditable 삽입 성공 시 true를 반환해야 한다."""
        pattern = re.compile(
            r"target\.appendChild\(caption\)[\s\S]{0,300}?return true",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "tryMobileWriteInsert contenteditable 경로에서 return true가 없음"
        )

    def test_try_mobile_write_insert_returns_result_eq_ok_for_textarea(self, ff_content_js):
        """tryMobileWriteInsert textarea 경로는 result === 'ok' 기준으로 반환해야 한다."""
        assert 'return result === "ok"' in ff_content_js

    def test_try_mobile_write_insert_returns_false_on_no_target(self, ff_content_js):
        """tryMobileWriteInsert가 타겟 없을 때 false를 반환해야 한다."""
        pattern = re.compile(
            r"no write area found[\s\S]{0,50}?return false",
            re.MULTILINE
        )
        assert pattern.search(ff_content_js), (
            "tryMobileWriteInsert: no write area found 후 return false 없음"
        )

    def test_contenteditable_existing_check_normalized(self, ff_content_js):
        """contenteditable 중복 감지에서 공백 정규화를 거쳐야 한다."""
        assert 'replace(/\\s+/g, " ")' in ff_content_js

    def test_mobile_observer_path_separated(self, ff_content_js):
        """insertCaptionIfNeeded가 consumePendingRecordByFileName으로 pending을 확인해야 한다."""
        # observer 경로가 pending record를 consume해 중복을 막는 메커니즘 존재 확인
        assert "consumePendingRecordByFileName" in ff_content_js


class TestSecurityPolicy:

    def test_no_inner_html(self, ff_content_js):
        for line in ff_content_js.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            assert "innerHTML" not in stripped, f"innerHTML 코드 사용 발견: {stripped}"

    def test_no_eval(self, ff_content_js):
        assert "eval(" not in ff_content_js
