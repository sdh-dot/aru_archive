"""
Aru Archive 작업 마법사.

9단계 순서형 워크플로우로 작업 폴더 설정부터 분류 실행·결과 확인까지 안내한다.

  1. Paths
  2. Scan / Load
  3. Metadata Check
  4. Metadata Enrichment
  5. Dictionary / Tag Normalization
  6. Tag Reclassification
  7. Classification Preview
  8. Execute Classification
  9. Result / Undo

기존 버튼은 "고급 도구"로 유지되며, 이 wizard가 기본 진입점이다.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from core.subprocess_util import no_window_kwargs

from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.ui_action_text import PIXIV_META_LABEL, PIXIV_META_TOOLTIP, SCAN_BUTTON_LABEL, SCAN_TOOLTIP
from app.views.loading_overlay_dialog import LoadingOverlayDialog
from app.views.path_setup_dialog import PathSetupDialog

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing instrumentation helpers (wizard-local)
# ---------------------------------------------------------------------------

_TIMING_LOG = logging.getLogger("aru.timing")


def _log_phase(phase: str, elapsed_ms: float, **extra) -> None:
    """Emit a [TIMING] line for a single phase. Never raises."""
    try:
        suffix = " ".join(f"{k}={v}" for k, v in extra.items())
        msg = f"[TIMING] {phase} elapsed_ms={elapsed_ms:.1f}"
        if suffix:
            msg += " " + suffix
        _TIMING_LOG.debug(msg)
    except Exception:
        pass  # timing must never break the app


# ---------------------------------------------------------------------------
# 썸네일 캐시
# ---------------------------------------------------------------------------

class PreviewThumbnailCache:
    """160×160 QPixmap LRU 캐시."""

    _THUMB_SIZE = 160

    def __init__(self, max_items: int = 200) -> None:
        from collections import OrderedDict
        self._cache: "OrderedDict[str, Optional[QPixmap]]" = OrderedDict()
        self._max = max_items

    def load(self, path: str) -> Optional[QPixmap]:
        if path in self._cache:
            self._cache.move_to_end(path)
            return self._cache[path]
        px = self._read(path)
        self._cache[path] = px
        self._cache.move_to_end(path)
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return px

    def _read(self, path: str) -> Optional[QPixmap]:
        if not path or not Path(path).is_file():
            return None
        px = QPixmap(path)
        if px.isNull():
            return None
        return px.scaled(
            self._THUMB_SIZE, self._THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 내부 stack 구성. (internal_num, short_label, title) — 9개 패널 모두 보존.
# index 5 ("태그 재분류") 는 사용자에게 숨기지만 _stack 에는 그대로 들어 있다.
# short_label 과 title 은 사용자 표시 전용 한국어 텍스트.
_STEPS = [
    (1, "작업 폴더",      "작업 폴더 설정"),
    (2, "이미지 스캔",    "이미지 스캔"),
    (3, "메타데이터 확인", "메타데이터 확인"),
    (4, "메타데이터 보강", "메타데이터 보강"),
    (5, "분류 기준 선택", "분류 기준 선택"),
    (6, "태그 재분류",    "태그 재분류 (자동)"),
    (7, "분류 미리보기",  "분류 미리보기"),
    (8, "분류 실행",      "분류 실행"),
    (9, "결과 / 되돌리기", "결과 / 되돌리기"),
]

# Step 6 (index 5)은 헤더 버튼에서 숨긴다 — 패널 자체는 _stack에 유지.
_HIDDEN_STEP_INDICES = {5}


def _total_visible_steps() -> int:
    """사용자에게 표시되는 step 개수 (hidden 제외). 내부 stack 길이와 다를 수 있다."""
    return len(_STEPS) - len(_HIDDEN_STEP_INDICES)


def _visible_step_number(internal_idx: int) -> Optional[int]:
    """internal stack index → 1-based 사용자 표시 번호. hidden 이면 None.

    사용자에게 hidden step 이 끼어 있는 게 안 보이도록 visible step 만 1..N
    번호를 매긴다. 예: hidden index 5 → visible 6 = internal 6.
    """
    if internal_idx < 0 or internal_idx >= len(_STEPS):
        return None
    if internal_idx in _HIDDEN_STEP_INDICES:
        return None
    visible = 0
    for i in range(internal_idx + 1):
        if i in _HIDDEN_STEP_INDICES:
            continue
        visible += 1
    return visible


def _visible_step_button_label(internal_idx: int) -> Optional[str]:
    """헤더 버튼 텍스트. hidden step 이면 None (호출자는 버튼 setVisible(False))."""
    if internal_idx in _HIDDEN_STEP_INDICES:
        return None
    if internal_idx < 0 or internal_idx >= len(_STEPS):
        return None
    num = _visible_step_number(internal_idx)
    short = _STEPS[internal_idx][1]
    return f"{num}. {short}"


def _visible_step_title_text(internal_idx: int) -> str:
    """단계 제목 바 텍스트. visible step 은 '단계 N / Total: 제목', hidden step
    은 사용자 친화적인 자동-진행 표기 ('자동 진행 단계: 제목').
    """
    if internal_idx < 0 or internal_idx >= len(_STEPS):
        return ""
    title = _STEPS[internal_idx][2]
    if internal_idx in _HIDDEN_STEP_INDICES:
        return f"자동 진행 단계: {title}"
    num = _visible_step_number(internal_idx)
    total = _total_visible_steps()
    return f"단계 {num} / {total}: {title}"

_RISK_STYLE = {
    "low":    "color:#5CDB8F; font-weight:bold;",
    "medium": "color:#FFD166; font-weight:bold;",
    "high":   "color:#FF6B7A; font-weight:bold;",
}

_LOCALE_OPTIONS = [
    ("canonical", "canonical (변경 없음)"),
    ("ko", "한국어"),
    ("ja", "일본어"),
    ("en", "영어"),
]

_SCOPE_OPTIONS = [
    ("all_classifiable", "전체 분류 가능 항목"),
    ("current_filter",   "현재 목록 (메인 창 필터)"),
]


# ---------------------------------------------------------------------------
# 배경 스레드
# ---------------------------------------------------------------------------

class _ScanThread(QThread):
    log_msg  = Signal(str)
    done     = Signal(dict)   # {"new": N, "skipped": N, "failed": N}

    def __init__(self, data_dir: str, inbox: str, managed_dir: str, db_path: str, parent=None):
        super().__init__(parent)
        self._data_dir = data_dir
        self._inbox    = inbox
        self._managed_dir = managed_dir
        self._db_path  = db_path

    def run(self) -> None:
        from db.database import initialize_database
        from core.inbox_scanner import InboxScanner
        conn = initialize_database(self._db_path)
        try:
            scanner = InboxScanner(
                conn, self._data_dir, managed_dir=self._managed_dir, log_fn=self.log_msg.emit
            )
            result  = scanner.scan(self._inbox)
            conn.commit()
            self.done.emit({"new": result.new, "skipped": result.skipped, "failed": result.failed})
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 스캔 실패: {exc}")
            self.done.emit({"new": 0, "skipped": 0, "failed": 1})
        finally:
            conn.close()


class _EnrichThread(QThread):
    log_msg  = Signal(str)
    progress = Signal(int, int)  # (done, total)
    done     = Signal(dict)      # {"success": N, "failed": N, "skipped": N}

    def __init__(self, db_path: str, exiftool_path: Optional[str], parent=None, *, mode: str = "missing_only"):
        super().__init__(parent)
        self._db_path       = db_path
        self._exiftool_path = exiftool_path
        self._mode          = mode

    def run(self) -> None:
        from db.database import initialize_database
        from core.metadata_enricher import enrich_file_from_pixiv, _is_timing_enabled, build_enrichment_queue
        conn = initialize_database(self._db_path)
        try:
            file_ids = build_enrichment_queue(conn, mode=self._mode)
            total    = len(file_ids)

            # ---- queue-level summary (timing 활성 시에만 출력) ----
            _timing_on = _is_timing_enabled()
            if _timing_on:
                self._emit_queue_summary(conn)

            # per-file timings 누적 (timing 활성 시에만)
            _agg_sum: dict[str, float] = {}
            _agg_max: dict[str, float] = {}
            _n_with_timing = 0

            success = failed = skipped = 0
            for idx, file_id in enumerate(file_ids):
                self.progress.emit(idx + 1, total)
                try:
                    r = enrich_file_from_pixiv(conn, file_id, exiftool_path=self._exiftool_path)
                    if r.get("status") == "success":
                        success += 1
                    elif r.get("status") in ("no_artwork_id", "not_found", "missing_file"):
                        skipped += 1
                    else:
                        failed += 1

                    # timings 집계
                    _t = r.get("timings") or {}
                    if _t:
                        _n_with_timing += 1
                        for k, v in _t.items():
                            _agg_sum[k] = _agg_sum.get(k, 0.0) + float(v)
                            _agg_max[k] = max(_agg_max.get(k, 0.0), float(v))
                except Exception as exc:
                    self.log_msg.emit(f"[ERROR] 보강 실패 ({file_id[:8]}): {exc}")
                    failed += 1
            conn.commit()

            # ---- aggregate timing summary (timings를 받은 파일이 1건 이상일 때만) ----
            if _n_with_timing > 0:
                self._emit_timing_aggregate(_n_with_timing, _agg_sum, _agg_max)

            self.done.emit({"success": success, "failed": failed, "skipped": skipped})
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 보강 스레드 예외: {exc}")
            self.done.emit({"success": 0, "failed": 0, "skipped": 0})
        finally:
            conn.close()


class _LocalMetadataImportThread(QThread):
    log_msg = Signal(str)
    progress = Signal(int, int, str)
    done = Signal(dict)

    def __init__(
        self,
        db_path: str,
        data_dir: str,
        managed_dir: str,
        parent=None,
        *,
        mode: str = "missing_only",
    ):
        super().__init__(parent)
        self._db_path = db_path
        self._data_dir = data_dir
        self._managed_dir = managed_dir
        self._mode = mode

    def run(self) -> None:
        from db.database import initialize_database
        from core.inbox_scanner import InboxScanner

        conn = initialize_database(self._db_path)
        try:
            group_ids = self._load_target_group_ids(conn)
            total = len(group_ids)
            scanner = InboxScanner(
                conn,
                self._data_dir,
                managed_dir=self._managed_dir,
                log_fn=self.log_msg.emit,
            )

            success = failed = skipped = 0
            for index, group_id in enumerate(group_ids, start=1):
                self.progress.emit(index - 1, total, group_id)
                try:
                    result = scanner.reprocess_group(group_id)
                    if result == "new":
                        success += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    self.log_msg.emit(f"[ERROR] XMP/JSON 입력 실패 ({group_id[:8]}): {exc}")
                    failed += 1
                self.progress.emit(index, total, group_id)

            self.done.emit(
                {
                    "success": success,
                    "failed": failed,
                    "skipped": skipped,
                    "total": total,
                    "mode": self._mode,
                }
            )
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] XMP/JSON 일괄 입력 예외: {exc}")
            self.done.emit(
                {
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "total": 0,
                    "mode": self._mode,
                    "error": str(exc),
                }
            )
        finally:
            conn.close()

    def _load_target_group_ids(self, conn) -> list[str]:
        if self._mode == "missing_only":
            where = "g.metadata_sync_status = 'metadata_missing'"
        else:
            where = "1=1"

        rows = conn.execute(
            f"""
            SELECT g.group_id
            FROM artwork_groups g
            WHERE {where}
              AND EXISTS (
                  SELECT 1
                  FROM artwork_files af
                  WHERE af.group_id = g.group_id
                    AND af.file_role = 'original'
                    AND af.file_status = 'present'
              )
            ORDER BY g.indexed_at DESC
            """
        ).fetchall()
        return [row["group_id"] for row in rows]

    def _emit_queue_summary(self, conn) -> None:
        """enrich queue의 total/unique/multi-page/savings_potential을 UI + logger에 보고한다."""
        try:
            counts = conn.execute(
                "SELECT COUNT(*) AS total_files, "
                "       COUNT(DISTINCT ag.artwork_id) AS unique_artworks "
                "FROM artwork_files af "
                "JOIN artwork_groups ag ON ag.group_id = af.group_id "
                "WHERE ag.metadata_sync_status = 'metadata_missing' "
                "  AND ag.artwork_id IS NOT NULL AND ag.artwork_id != '' "
                "  AND af.file_role = 'original'"
            ).fetchone()
            multi_rows = conn.execute(
                "SELECT ag.artwork_id, COUNT(*) AS cnt "
                "FROM artwork_files af "
                "JOIN artwork_groups ag ON ag.group_id = af.group_id "
                "WHERE ag.metadata_sync_status = 'metadata_missing' "
                "  AND ag.artwork_id IS NOT NULL AND ag.artwork_id != '' "
                "  AND af.file_role = 'original' "
                "GROUP BY ag.artwork_id"
            ).fetchall()
        except Exception as exc:
            logger.debug("enrich queue summary 계산 실패 (무시): %s", exc)
            return

        total_files     = int(counts["total_files"] or 0) if counts else 0
        unique_artworks = int(counts["unique_artworks"] or 0) if counts else 0
        multi_page_files  = sum(int(r["cnt"]) for r in multi_rows if int(r["cnt"]) > 1)
        single_page_files = total_files - multi_page_files
        savings_potential = max(0, total_files - unique_artworks)

        self.log_msg.emit(
            f"[INFO] enrich queue: {total_files} files / "
            f"{unique_artworks} unique artworks "
            f"(multi-page: {multi_page_files} files, single-page: {single_page_files}). "
            f"이론상 fetch 절약 가능: {savings_potential}건."
        )
        logger.info(
            "enrich_queue_summary total=%d unique=%d multi=%d single=%d savings_potential=%d",
            total_files, unique_artworks, multi_page_files, single_page_files,
            savings_potential,
        )

    def _emit_timing_aggregate(
        self,
        n_with_timing: int,
        agg_sum: dict,
        agg_max: dict,
    ) -> None:
        """per-file timing 누적치를 평균/최대로 변환해 UI + logger에 1회 출력한다."""
        avg_fetch    = agg_sum.get("pixiv_fetch", 0.0) / n_with_timing
        avg_xmp      = agg_sum.get("write_xmp", 0.0) / n_with_timing
        avg_total    = agg_sum.get("total", 0.0) / n_with_timing
        max_fetch    = agg_max.get("pixiv_fetch", 0.0)
        max_xmp      = agg_max.get("write_xmp", 0.0)
        max_total    = agg_max.get("total", 0.0)

        self.log_msg.emit(
            f"[INFO] enrich timing summary (n={n_with_timing}): "
            f"평균 fetch={avg_fetch:.2f}s write_xmp={avg_xmp:.2f}s total={avg_total:.2f}s "
            f"(최대 fetch={max_fetch:.2f}s, write_xmp={max_xmp:.2f}s, total={max_total:.2f}s)"
        )
        logger.info(
            "enrich_summary n=%d avg_fetch=%.3fs avg_xmp=%.3fs avg_total=%.3fs "
            "max_fetch=%.3fs max_xmp=%.3fs max_total=%.3fs",
            n_with_timing, avg_fetch, avg_xmp, avg_total,
            max_fetch, max_xmp, max_total,
        )


class _RetagThread(QThread):
    log_msg = Signal(str)
    done    = Signal(list)   # list of per-group result dicts

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path

    def run(self) -> None:
        from db.database import initialize_database
        from core.tag_reclassifier import retag_groups_from_existing_tags
        conn = initialize_database(self._db_path)
        try:
            rows = conn.execute(
                "SELECT g.group_id, g.artwork_title, "
                "       g.series_tags_json, g.character_tags_json, "
                "       (SELECT f.file_path FROM artwork_files f "
                "        WHERE f.group_id = g.group_id AND f.file_role = 'original' "
                "        LIMIT 1) AS file_path "
                "FROM artwork_groups g ORDER BY g.indexed_at DESC"
            ).fetchall()

            before: dict[str, dict] = {}
            for r in rows:
                before[r["group_id"]] = {
                    "title":     r["artwork_title"] or "",
                    "filename":  Path(r["file_path"] or "").name,
                    "series":    json.loads(r["series_tags_json"] or "[]"),
                    "character": json.loads(r["character_tags_json"] or "[]"),
                }

            group_ids = [r["group_id"] for r in rows]
            summary = retag_groups_from_existing_tags(conn, group_ids)

            after: dict[str, dict] = {}
            if group_ids:
                placeholders = ",".join("?" * len(group_ids))
                for r in conn.execute(
                    f"SELECT group_id, series_tags_json, character_tags_json "
                    f"FROM artwork_groups WHERE group_id IN ({placeholders})",
                    group_ids,
                ).fetchall():
                    after[r["group_id"]] = {
                        "series":    json.loads(r["series_tags_json"] or "[]"),
                        "character": json.loads(r["character_tags_json"] or "[]"),
                    }

            error_ids: set[str] = set()
            for err_str in summary.get("errors", []):
                prefix = err_str.split(":")[0].strip()
                for gid in group_ids:
                    if gid.startswith(prefix):
                        error_ids.add(gid)

            results: list[dict] = []
            for gid in group_ids:
                b = before.get(gid, {})
                a = after.get(gid, {})
                b_s = b.get("series", [])
                b_c = b.get("character", [])
                a_s = a.get("series", [])
                a_c = a.get("character", [])
                is_error = gid in error_ids
                changed  = not is_error and (b_s != a_s or b_c != a_c)
                status   = "오류" if is_error else ("변경됨" if changed else "변경 없음")
                note     = next(
                    (e.split(":", 1)[1].strip() for e in summary.get("errors", []) if e.startswith(gid[:8])),
                    "",
                )
                results.append({
                    "group_id":         gid,
                    "filename":         b.get("filename", ""),
                    "title":            b.get("title", ""),
                    "before_series":    ", ".join(b_s),
                    "before_character": ", ".join(b_c),
                    "after_series":     ", ".join(a_s),
                    "after_character":  ", ".join(a_c),
                    "changed":          changed,
                    "status":           status,
                    "note":             note,
                })

            self.done.emit(results)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 태그 재분류 실패: {exc}")
            self.done.emit([])
        finally:
            conn.close()


_INFERENCE_REASON_PREFIX = "[추론]"
_INFERENCE_MAX_REASONS = 3


def _format_inference_reason(candidate) -> str:
    """단일 inference 후보를 짧은 reason 문자열로 변환한다.

    표시 정책 예시:
        [추론] 캐릭터 ワカモ → Blue Archive 후보 (high, built_in_pack:test)
        [추론] 캐릭터 リクハチマ→ Blue Archive 후보 (medium, built_in) · 장음부호 variant
        [추론] 캐릭터 리쿠하치마 아루 → Blue Archive 후보 (medium, imported_localized_pack) · ko localized
    """
    label = "high" if candidate.confidence == "high" else "medium"
    src = candidate.source or "unknown"
    base = (
        f"{_INFERENCE_REASON_PREFIX} 캐릭터 {candidate.raw_tag} → "
        f"{candidate.parent_series} 후보 ({label}, {src})"
    )
    kind = candidate.match_kind or ""
    if "long_vowel" in kind:
        base += " · 장음부호 variant"
    elif candidate.locale:
        base += f" · {candidate.locale} localized"
    return base


def _summarize_inference_for_preview(conn, raw_tags) -> list:
    """raw_tags 에 대해 read-only character/series 추론 reason 문자열을 반환한다.

    - 분류 결과나 destination path 를 절대 변경하지 않는다.
    - high / medium confidence character 후보만 표시한다 (low 는 노이즈).
    - 같은 (raw, parent_series) 중복 reason 은 1번만.
    - 상위 ``_INFERENCE_MAX_REASONS`` 개를 표시하고 나머지는 "외 N건" 으로 요약.
    - 같은 canonical 에 다른 parent_series 가 매칭되면 ambiguous 안내를 맨 위에.
    - parent_series 가 비었지만 character 후보가 있으면 보조 안내 1줄 추가.
    - 호출 실패는 silent fallback (preview 자체 실패는 막아야 함).
    """
    if not raw_tags:
        return []
    try:
        from core.classification_inference import (
            has_ambiguous_parent_series,
            infer_character_series_candidates,
        )
        candidates = infer_character_series_candidates(conn, list(raw_tags))
    except Exception:
        return []

    if not candidates:
        return []

    char_candidates = [c for c in candidates if c.tag_type == "character"]
    if not char_candidates:
        return []

    reasons: list[str] = []

    # 1. ambiguity 경고 — 자동 적용 막기 위한 사용자 안내.
    if has_ambiguous_parent_series(char_candidates):
        reasons.append(
            f"{_INFERENCE_REASON_PREFIX} 서로 다른 parent_series 후보가 있어 자동 적용 보류"
        )

    # 2. 상위 후보 reason — high / medium 만, parent_series 가 있는 것만, 중복 제거.
    qualifying = [
        c for c in char_candidates
        if c.confidence in ("high", "medium") and c.parent_series
    ]
    seen_keys: set = set()
    shown = 0
    extra = 0
    for c in qualifying:
        key = (c.raw_tag, c.parent_series)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if shown >= _INFERENCE_MAX_REASONS:
            extra += 1
            continue
        reasons.append(_format_inference_reason(c))
        shown += 1

    if extra > 0:
        reasons.append(f"{_INFERENCE_REASON_PREFIX} 외 {extra}건")

    # 3. parent_series 없는 character 후보만 있을 때 보조 안내.
    if shown == 0 and any(
        c.tag_type == "character"
        and (not c.parent_series)
        and c.confidence in ("high", "medium")
        for c in char_candidates
    ):
        reasons.append(
            f"{_INFERENCE_REASON_PREFIX} 캐릭터 후보는 있으나 parent_series 없음"
        )

    return reasons


def _augment_previews_with_inference_reasons(conn, previews) -> None:
    """preview 항목에 ``inference_reasons`` 필드를 in-place 로 주입한다.

    각 preview 의 ``group_id`` 로 ``artwork_groups.tags_json`` 을 읽어
    inference 를 수행한다. preview 의 destinations / classification_info 는
    절대 수정하지 않는다. 호출 실패는 silent skip.
    """
    if not previews:
        return
    for preview in previews:
        if not isinstance(preview, dict):
            continue
        if "inference_reasons" in preview:
            continue  # 이미 주입돼 있으면 덮어쓰지 않음
        group_id = preview.get("group_id")
        if not group_id:
            preview["inference_reasons"] = []
            continue
        raw_tags: list = []
        try:
            row = conn.execute(
                "SELECT tags_json FROM artwork_groups WHERE group_id = ?",
                (group_id,),
            ).fetchone()
            if row is not None:
                raw_json = row["tags_json"] if hasattr(row, "keys") else row[0]
                if raw_json:
                    parsed = json.loads(raw_json)
                    if isinstance(parsed, list):
                        raw_tags = [str(t) for t in parsed if t]
        except Exception:
            raw_tags = []
        preview["inference_reasons"] = _summarize_inference_for_preview(conn, raw_tags)


class _PreviewThread(QThread):
    log_msg = Signal(str)
    done    = Signal(dict)

    def __init__(self, conn_factory, group_ids: list[str], config: dict, parent=None):
        super().__init__(parent)
        self._factory   = conn_factory
        self._group_ids = group_ids
        self._config    = config

    def run(self) -> None:
        from core.batch_classifier import build_classify_batch_preview
        conn = self._factory()
        try:
            result = build_classify_batch_preview(conn, self._group_ids, self._config)
            # Read-only 추론 reason 을 preview dict 에 추가.
            # destination path / classification_info / 실행 단계에 영향 없음.
            try:
                _augment_previews_with_inference_reasons(conn, result.get("previews", []))
            except Exception as exc:
                self.log_msg.emit(f"[WARN] 추론 reason 생성 실패: {exc}")
            self.done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 미리보기 실패: {exc}")
            self.done.emit({})
        finally:
            conn.close()


class _ExecuteThread(QThread):
    log_msg = Signal(str)
    progress = Signal(int, int, str)
    done    = Signal(dict)

    def __init__(self, conn_factory, batch_preview: dict, config: dict, parent=None):
        super().__init__(parent)
        self._factory       = conn_factory
        self._batch_preview = batch_preview
        self._config        = config

    def run(self) -> None:
        from core.batch_classifier import execute_classify_batch
        conn = self._factory()
        try:
            total = len(self._batch_preview.get("previews", []))
            self.log_msg.emit(f"[INFO] 일괄 분류 실행 시작: {total}개 그룹")

            def _progress(done: int, total_groups: int, group_id: str, status: str) -> None:
                label = {
                    "running": "처리 중",
                    "ok":      "완료",
                    "error":   "오류",
                }.get(status, status)
                self.progress.emit(done, total_groups, f"{label}: {group_id[:8]}…")
                if status != "running":
                    self.log_msg.emit(
                        f"[INFO] 분류 진행: {done}/{total_groups} — {label} ({group_id[:8]}…)"
                    )

            result = execute_classify_batch(
                conn, self._batch_preview, self._config, progress_fn=_progress
            )
            self.done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 실행 실패: {exc}")
            self.done.emit({"success": False, "error": str(exc)})
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _h_sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _label(text: str, bold: bool = False) -> QLabel:
    lbl = QLabel(text)
    if bold:
        lbl.setStyleSheet("font-weight: bold;")
    return lbl


def _kv_table(rows: list[tuple[str, str]]) -> QTableWidget:
    """키-값 2열 테이블을 생성한다."""
    tbl = QTableWidget(len(rows), 2)
    tbl.setHorizontalHeaderLabels(["항목", "값"])
    tbl.horizontalHeader().setStretchLastSection(True)
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    tbl.setMaximumHeight(min(len(rows) * 26 + 30, 360))
    for r, (k, v) in enumerate(rows):
        tbl.setItem(r, 0, QTableWidgetItem(k))
        tbl.setItem(r, 1, QTableWidgetItem(str(v)))
    return tbl


def _fmt_size(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / (1024 ** 3):.1f} GB"
    if b >= 1024 ** 2:
        return f"{b / (1024 ** 2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


# ---------------------------------------------------------------------------
# 개별 단계 패널
# ---------------------------------------------------------------------------

class _StepPanel(QWidget):
    """모든 단계 패널의 기반 클래스."""

    log_msg = Signal(str)
    refresh_main = Signal()   # MainWindow에 갱신 요청

    def __init__(self, wizard: "WorkflowWizardView", parent=None):
        super().__init__(parent)
        self._wizard = wizard

    def _conn_factory(self):
        return self._wizard._conn_factory()

    def _config(self) -> dict:
        return self._wizard._config

    def _db_path(self) -> str:
        return self._wizard._db_path()

    def _show_loading(
        self,
        title: str,
        message: str,
        *,
        detail: str = "",
        total: Optional[int] = None,
        current: int = 0,
    ) -> None:
        self._wizard._show_loading(
            title,
            message,
            detail=detail,
            total=total,
            current=current,
        )

    def _update_loading(
        self,
        *,
        message: Optional[str] = None,
        detail: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        self._wizard._update_loading(
            message=message,
            detail=detail,
            current=current,
            total=total,
        )

    def _hide_loading(self) -> None:
        self._wizard._hide_loading()

    def _mirror_loading_log(self, message: str) -> None:
        self._wizard._mirror_loading_log(message)

    def refresh(self) -> None:
        """단계 데이터 새로고침. 서브클래스에서 오버라이드."""


# ── Step 1: Workspace Paths ─────────────────────────────────────────────────

class _Step1Root(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("작업 폴더 설정", bold=True))
        layout.addWidget(_h_sep())

        # Wizard 작업 범위 안내 — 분류 대상과 Pixiv 가져오기 대상이 서로
        # 다른 정책임을 명시. "Pixiv 파일만" 같은 단정 표현은 회피 — XMP
        # 입력 / 분류 미리보기·실행 등은 비-Pixiv 파일도 대상으로 한다.
        # UI-only — wizard 의 실제 분류 / metadata 로직은 변경 없음.
        self._scope_notice = QLabel(
            "작업 범위: 메타데이터가 등록되었거나 Pixiv 기준으로 처리 가능한 "
            "이미지 파일을 대상으로 합니다.\n"
            "Pixiv 메타데이터 가져오기는 Pixiv 출처 파일에만 적용됩니다."
        )
        self._scope_notice.setObjectName("step1ScopeNotice")
        self._scope_notice.setWordWrap(True)
        self._scope_notice.setStyleSheet(
            "color: #8F8890; font-size: 11px; padding: 4px 0px;"
        )
        layout.addWidget(self._scope_notice)

        guide = QLabel(
            "선택한 폴더는 분류 대상 폴더로 그대로 사용됩니다.\n"
            "같은 위치에 Classified / Managed 폴더가 자동 생성됩니다.\n"
            "앱 내부 데이터(DB, 로그, 썸네일)는 사용자 홈의 AruArchive 아래에 저장됩니다."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)

        self._status_table = QTableWidget(0, 2)
        self._status_table.setHorizontalHeaderLabels(["항목", "상태"])
        self._status_table.horizontalHeader().setStretchLastSection(True)
        self._status_table.verticalHeader().setVisible(False)
        self._status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._status_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self._status_table)

        btn_row = QHBoxLayout()
        btn_select = QPushButton("📁 작업 폴더 설정")
        btn_open   = QPushButton("📂 폴더 열기")
        btn_select.clicked.connect(self._on_select_root)
        btn_open  .clicked.connect(self._on_open_folder)
        btn_row.addWidget(btn_select)
        btn_row.addWidget(btn_open)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

    def refresh(self) -> None:
        cfg = self._config()
        data_dir = cfg.get("data_dir", "")
        inbox    = cfg.get("inbox_dir", "")
        classified = cfg.get("classified_dir", "")
        managed = cfg.get("managed_dir", "")
        db_path  = cfg.get("db", {}).get("path") or (
            f"{data_dir}/.runtime/aru_archive.db" if data_dir else ""
        )

        def _chk(path: str) -> str:
            if not path:
                return "⚠ 미설정"
            return "✅ 존재" if Path(path).exists() else "❌ 없음"

        db_ok = False
        if db_path and Path(db_path).exists():
            try:
                from db.database import initialize_database
                c = initialize_database(db_path)
                c.execute("SELECT 1 FROM artwork_groups LIMIT 1")
                c.close()
                db_ok = True
            except Exception:
                pass

        rows = [
            ("앱 데이터 폴더",  data_dir or "미설정"),
            ("분류 대상 폴더",  inbox or "미설정"),
            ("분류 대상 상태",  _chk(inbox)),
            ("분류 완료 폴더",  classified or "미설정"),
            ("분류 완료 상태",  _chk(classified)),
            ("관리 폴더",      managed or "미설정"),
            ("관리 폴더 상태",  _chk(managed)),
            (".thumbcache",   _chk(f"{data_dir}/.thumbcache" if data_dir else "")),
            (".runtime",      _chk(f"{data_dir}/.runtime" if data_dir else "")),
            ("DB 파일",       "✅ 정상" if db_ok else ("❌ 연결 실패" if db_path else "⚠ 미설정")),
        ]
        self._status_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self._status_table.setItem(r, 0, QTableWidgetItem(k))
            self._status_table.setItem(r, 1, QTableWidgetItem(v))

    def _on_select_root(self) -> None:
        cfg   = self._config()
        start = cfg.get("inbox_dir") or str(Path.home())
        dlg = PathSetupDialog(start_dir=start, data_dir=cfg.get("data_dir", ""), parent=self)
        if dlg.exec() != PathSetupDialog.DialogCode.Accepted:
            return
        from core.config_manager import (
            ensure_app_directories, ensure_workspace_directories,
            save_config, update_workspace_from_inbox,
        )
        paths = dlg.selected_paths()
        if not paths:
            return
        update_workspace_from_inbox(cfg, paths["inbox_dir"])
        ensure_app_directories(cfg)
        ensure_workspace_directories(cfg)
        try:
            save_config(cfg, self._wizard._config_path)
        except Exception as exc:
            logger.warning("config 저장 실패: %s", exc)
        self.refresh()
        self.refresh_main.emit()

    def _on_open_folder(self) -> None:
        inbox_dir = self._config().get("inbox_dir", "")
        if not inbox_dir:
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", inbox_dir], **no_window_kwargs())
            elif sys.platform == "darwin":
                subprocess.Popen(["open", inbox_dir])
            else:
                subprocess.Popen(["xdg-open", inbox_dir])
        except Exception as exc:
            logger.warning("폴더 열기 실패: %s", exc)


# ── Step 2: Scan / Load ─────────────────────────────────────────────────────

class _Step2Scan(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("이미지 스캔 / 파일 로드", bold=True))
        layout.addWidget(_h_sep())

        self._tbl = _kv_table([])
        layout.addWidget(self._tbl)

        self._last_result_lbl = QLabel("")
        layout.addWidget(self._last_result_lbl)

        btn_row = QHBoxLayout()
        self._btn_scan = QPushButton(SCAN_BUTTON_LABEL)
        self._btn_scan.setToolTip(SCAN_TOOLTIP)
        self._btn_scan.clicked.connect(self._on_scan)
        btn_row.addWidget(self._btn_scan)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        self._scan_thread: Optional[_ScanThread] = None

    def refresh(self) -> None:
        cfg      = self._config()
        data_dir = cfg.get("data_dir", "")
        inbox    = cfg.get("inbox_dir", "")
        db_path  = self._db_path()

        total_groups = files_count = inbox_files = 0
        ext_counts: dict = {}
        try:
            conn = self._conn_factory()
            row  = conn.execute("SELECT COUNT(*) FROM artwork_groups").fetchone()
            total_groups = row[0] if row else 0
            row  = conn.execute("SELECT COUNT(*) FROM artwork_files").fetchone()
            files_count = row[0] if row else 0
            for r in conn.execute(
                "SELECT file_format, COUNT(*) AS cnt FROM artwork_files GROUP BY file_format"
            ).fetchall():
                ext_counts[r["file_format"]] = r["cnt"]
            conn.close()
        except Exception:
            pass

        if inbox and Path(inbox).exists():
            inbox_files = sum(
                1 for p in Path(inbox).rglob("*")
                if p.is_file() and p.suffix.lower() in
                   {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".zip"}
            )

        rows: list[tuple[str, str]] = [
            ("Inbox 폴더",        inbox or "미설정"),
            ("Inbox 파일 수",     str(inbox_files)),
            ("DB artwork_groups", str(total_groups)),
            ("DB artwork_files",  str(files_count)),
        ]
        for ext, cnt in sorted(ext_counts.items()):
            rows.append((f"  {ext.upper()}", str(cnt)))

        self._tbl.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self._tbl.setItem(r, 0, QTableWidgetItem(k))
            self._tbl.setItem(r, 1, QTableWidgetItem(v))

    def _on_scan(self) -> None:
        if self._scan_thread and self._scan_thread.isRunning():
            return
        cfg      = self._config()
        data_dir = cfg.get("data_dir", "")
        inbox    = cfg.get("inbox_dir", "")
        db_path  = self._db_path()
        if not inbox:
            QMessageBox.warning(self, "설정 필요", "먼저 작업 폴더를 설정하세요.")
            return
        self._btn_scan.setEnabled(False)
        self._btn_scan.setText("스캔 중…")
        self._show_loading(
            "Step 2: 이미지 스캔",
            "Inbox 이미지를 스캔하고 DB를 갱신하는 중입니다…",
            detail="파일 수가 많으면 시간이 조금 걸릴 수 있습니다.",
            total=None,
        )
        self._scan_thread = _ScanThread(data_dir, inbox, cfg.get("managed_dir", ""), db_path, self)
        self._scan_thread.log_msg.connect(self.log_msg)
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.scan")
        self._hide_loading()
        self._btn_scan.setEnabled(True)
        self._btn_scan.setText("🔍 이미지 스캔 실행")
        self._last_result_lbl.setText(
            f"완료 — 신규: {result['new']}, 스킵: {result['skipped']}, 실패: {result['failed']}"
        )
        _log_phase("postprocess.start", 0.0, op="wizard.scan")
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.scan")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.scan")


# ── Step 3: Metadata Check ──────────────────────────────────────────────────

class _Step3Meta(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("파일 상태 분석", bold=True))
        layout.addWidget(_h_sep())

        self._tbl = _kv_table([])
        layout.addWidget(self._tbl)

        self._warnings_lbl = QLabel("")
        self._warnings_lbl.setWordWrap(True)
        layout.addWidget(self._warnings_lbl)

        # ── Optional: 중복 검사 섹션 ──
        layout.addWidget(_h_sep())
        layout.addWidget(_label("중복 검사 (선택 사항)", bold=True))
        self._dup_status_lbl = QLabel(
            "중복 검사는 메인 화면의 기존 중복 검사 흐름으로 실행됩니다. "
            "범위 선택, 확인, 결과 검토는 동일한 창에서 진행됩니다."
        )
        self._dup_status_lbl.setWordWrap(True)
        self._dup_status_lbl.setStyleSheet("color: #8F6874; font-size: 11px;")
        layout.addWidget(self._dup_status_lbl)

        dup_btn_row = QHBoxLayout()
        self._btn_exact_dup  = QPushButton("🧬 완전 중복 검사")
        self._btn_visual_dup = QPushButton("👁 시각적 중복 검사")
        for btn in (self._btn_exact_dup, self._btn_visual_dup):
            btn.setStyleSheet(
                "QPushButton { background: #2B1720; color: #D8AEBB; "
                "padding: 4px 10px; border-radius: 4px; }"
                "QPushButton:hover { background: #3A202B; }"
            )
        dup_btn_row.addWidget(self._btn_exact_dup)
        dup_btn_row.addWidget(self._btn_visual_dup)
        dup_btn_row.addStretch()
        layout.addLayout(dup_btn_row)

        self._btn_exact_dup .clicked.connect(self._on_exact_dup)
        self._btn_visual_dup.clicked.connect(self._on_visual_dup)

        layout.addStretch()

    def refresh(self) -> None:
        from core.workflow_summary import build_workflow_file_status_summary, classify_workflow_warnings
        try:
            conn = self._conn_factory()
            fs   = build_workflow_file_status_summary(conn)
            conn.close()
        except Exception as exc:
            self._tbl.setRowCount(1)
            self._tbl.setItem(0, 0, QTableWidgetItem("오류"))
            self._tbl.setItem(0, 1, QTableWidgetItem(str(exc)))
            return

        status_counts = fs.get("metadata_status_counts", {})
        rows: list[tuple[str, str]] = [
            ("총 작품 수",           str(fs.get("total_groups", 0))),
            ("Inbox 상태",          str(fs.get("inbox_count", 0))),
            ("Classified 상태",     str(fs.get("classified_count", 0))),
            ("분류 가능",            str(fs.get("classifiable", 0))),
            ("분류 제외",            str(fs.get("excluded", 0))),
            ("XMP 기록 가능",        str(fs.get("xmp_capable", 0))),
            ("Pixiv ID 보유",        str(fs.get("pixiv_id_extractable", 0))),
            ("Pixiv ID 없음",        str(fs.get("pixiv_id_missing", 0))),
        ]
        for status, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
            rows.append((f"  {status}", str(cnt)))

        self._tbl.setRowCount(len(rows))
        self._tbl.setMaximumHeight(min(len(rows) * 26 + 30, 400))
        for r, (k, v) in enumerate(rows):
            self._tbl.setItem(r, 0, QTableWidgetItem(k))
            self._tbl.setItem(r, 1, QTableWidgetItem(v))

        try:
            from core.workflow_summary import build_dictionary_status_summary
            conn2 = self._conn_factory()
            ds    = build_dictionary_status_summary(conn2)
            conn2.close()
            warns = classify_workflow_warnings(fs, ds)
        except Exception:
            warns = []

        if warns:
            txt = "\n".join(
                f"{'⚠' if w['level']=='warning' else ('❌' if w['level']=='danger' else 'ℹ')} {w['message']}"
                for w in warns
            )
            self._warnings_lbl.setText(txt)
        else:
            self._warnings_lbl.setText("✅ 상태 이상 없음")

    def _on_exact_dup(self) -> None:
        """완전 중복 검사를 MainWindow handler에 위임한다.

        Step 3 자체 로직(scope/confirm/dialog)은 보유하지 않고, 상위 wizard의
        signal만 emit해 Top Menu와 동일한 흐름(scope 선택 + summary +
        DeletePreviewDialog)으로 진행하게 한다.
        """
        self._wizard.exact_duplicate_scan_requested.emit()

    def _on_visual_dup(self) -> None:
        """시각적 중복 검사를 MainWindow handler에 위임한다.

        Step 3 자체 로직(confirm_visual_scan/threshold/dialog)은 보유하지
        않고, 상위 wizard의 signal만 emit해 Top Menu와 동일한 흐름으로
        진행하게 한다.
        """
        self._wizard.visual_duplicate_scan_requested.emit()


# ── Step 4: Metadata Enrichment ─────────────────────────────────────────────

class _Step4Enrich(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("메타데이터 보강 (Pixiv)", bold=True))
        layout.addWidget(_h_sep())

        self._tbl = _kv_table([])
        layout.addWidget(self._tbl)

        self._progress_lbl = QLabel("")
        layout.addWidget(self._progress_lbl)

        layout.addWidget(QLabel(
            "ℹ '메타데이터 없는 항목만 보강'은 metadata_missing 상태만 처리합니다.\n"
            "  '전체 보강'은 metadata_write_failed / xmp_write_failed / json_only도 다시 처리합니다.\n"
            "  source_unavailable / full / pending은 두 모드 모두 제외됩니다."
        ))

        btn_row = QHBoxLayout()
        self._btn_enrich = QPushButton("🔄 메타데이터 없는 항목만 보강")
        self._btn_enrich.setToolTip(
            "이미 메타데이터가 있는 항목은 건너뛰고, 비어 있는 항목만 보강합니다."
        )
        self._btn_enrich.clicked.connect(self._on_enrich_missing)
        btn_row.addWidget(self._btn_enrich)

        self._btn_enrich_all = QPushButton("🔁 Pixiv ID 있는 모든 항목 재시도")
        self._btn_enrich_all.setToolTip(
            "오류·부분 처리된 항목까지 포함해 다시 보강합니다. 시간이 더 걸릴 수 있습니다."
        )
        self._btn_enrich_all.clicked.connect(self._on_enrich_all)
        btn_row.addWidget(self._btn_enrich_all)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        self._enrich_thread: Optional[_EnrichThread] = None

    def refresh(self) -> None:
        from core.workflow_summary import build_workflow_file_status_summary
        try:
            conn = self._conn_factory()
            fs   = build_workflow_file_status_summary(conn)
            conn.close()
        except Exception:
            return
        missing  = fs.get("metadata_status_counts", {}).get("metadata_missing", 0)
        rows = [
            ("metadata_missing",      str(missing)),
            ("Pixiv ID 있음 (보강 가능)", str(fs.get("pixiv_id_extractable", 0))),
            ("Pixiv ID 없음",         str(fs.get("pixiv_id_missing", 0))),
        ]
        self._tbl.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self._tbl.setItem(r, 0, QTableWidgetItem(k))
            self._tbl.setItem(r, 1, QTableWidgetItem(v))

    def _on_enrich_missing(self) -> None:
        """기존 동작 — metadata_missing만 보강."""
        self._start_enrich(mode="missing_only")

    def _on_enrich_all(self) -> None:
        """전체 보강 — confirm 후 시작."""
        if self._enrich_thread and self._enrich_thread.isRunning():
            return

        # 처리 대상 수 계산
        try:
            conn = self._conn_factory()
            try:
                from core.metadata_enricher import build_enrichment_queue
                count = len(build_enrichment_queue(conn, mode="all_pixiv"))
            finally:
                conn.close()
        except Exception as exc:
            self.log_msg.emit(f"[WARN] 전체 보강 큐 계산 실패: {exc}")
            return

        if count == 0:
            QMessageBox.information(
                self, "전체 보강",
                "전체 보강 대상이 없습니다.",
            )
            return

        msg = (
            "전체 보강은 Pixiv ID가 있는 항목 중 metadata_missing, "
            "metadata_write_failed, xmp_write_failed, json_only 상태를 "
            "다시 처리합니다.\n"
            "full, source_unavailable, pending 상태는 제외됩니다.\n"
            f"처리 대상: {count}건.\n"
            "기존 JSON/XMP가 다시 작성될 수 있습니다. 계속할까요?"
        )
        reply = QMessageBox.question(
            self, "전체 보강 확인", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._start_enrich(mode="all_pixiv")

    def _start_enrich(self, *, mode: str) -> None:
        """공통 thread 시작 로직."""
        if self._enrich_thread and self._enrich_thread.isRunning():
            return
        db_path = self._db_path()
        from core.exiftool_resolver import resolve_exiftool_path
        exiftool = resolve_exiftool_path(self._config())
        self._btn_enrich.setEnabled(False)
        self._btn_enrich_all.setEnabled(False)
        self._btn_enrich.setText("보강 중…")
        self._enrich_thread = _EnrichThread(db_path, exiftool, self, mode=mode)
        self._enrich_thread.log_msg.connect(self.log_msg)
        self._enrich_thread.progress.connect(
            lambda done, total: self._progress_lbl.setText(f"진행: {done}/{total}")
        )
        self._enrich_thread.done.connect(self._on_enrich_done)
        self._enrich_thread.start()

    def _on_enrich_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.enrich_legacy")
        self._btn_enrich.setEnabled(True)
        self._btn_enrich_all.setEnabled(True)
        self._btn_enrich.setText("🔄 메타데이터 없는 항목만 보강")
        self._progress_lbl.setText(
            f"완료 — 성공: {result['success']}, 실패: {result['failed']}, 스킵: {result['skipped']}"
        )
        _log_phase("postprocess.start", 0.0, op="wizard.enrich_legacy")
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.enrich_legacy")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.enrich_legacy")


# ── Step 5: 분류 기준 선택 ───────────────────────────────────────────────────

class _Step4EnrichModern(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        self._selected_scope = "missing_only"
        self._pending_bulk_followup: Optional[str] = None
        self._status_cards: dict[str, QLabel] = {}
        self._enrich_thread: Optional[_EnrichThread] = None
        self._local_import_thread: Optional[_LocalMetadataImportThread] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(_label("Step 4: 메타데이터 보강", bold=True))
        section_title = QLabel("메타데이터 보강 (옵션 설정)")
        section_title.setStyleSheet("font-size:16px; font-weight:bold; color:#F3C7D3;")
        layout.addWidget(section_title)
        first_item = layout.itemAt(0)
        if first_item and first_item.widget():
            first_item.widget().hide()
        layout.addWidget(_h_sep())

        self._progress_lbl = QLabel("")
        self._progress_lbl.setWordWrap(True)
        self._progress_lbl.setStyleSheet("color:#D8AEBB; font-size:12px;")
        layout.addWidget(self._progress_lbl)
        self._progress_lbl.hide()
        self._progress_lbl.hide()

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.hide()
        self._progress.setStyleSheet(
            "QProgressBar {"
            " background:#180D12; color:#F7E8EC; border:1px solid #6C3145; "
            " border-radius:8px; text-align:center; min-height:18px; }"
            "QProgressBar::chunk { background:#D06A86; border-radius:7px; }"
        )
        layout.addWidget(self._progress)
        self._progress.hide()
        self._progress.hide()

        layout.addWidget(self.create_condition_section())
        layout.addWidget(self.create_action_section())
        layout.addWidget(self.create_warning_box())
        layout.addWidget(self.create_status_summary_section())
        layout.addStretch()

    def create_condition_section(self) -> QWidget:
        card = self._make_card_frame()
        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        title = QLabel("일괄 적용 조건")
        title.setStyleSheet("font-size:14px; font-weight:bold; color:#F3C7D3;")
        layout.addWidget(title)

        self._scope_group = QButtonGroup(self)

        self._radio_missing = QRadioButton("메타데이터가 없는 항목만")
        self._radio_missing.setChecked(True)
        self._radio_missing.toggled.connect(
            lambda checked: checked and self._set_selected_scope("missing_only")
        )
        self._scope_group.addButton(self._radio_missing)
        layout.addWidget(self._radio_missing)
        layout.addWidget(self._make_hint_label("metadata_missing 상태의 항목만 처리합니다."))

        self._radio_all = QRadioButton("전체 적용")
        self._radio_all.toggled.connect(
            lambda checked: checked and self._set_selected_scope("all")
        )
        self._scope_group.addButton(self._radio_all)
        layout.addWidget(self._radio_all)
        layout.addWidget(self._make_hint_label("모든 항목에 대해 다시 조회하고 덮어씁니다."))

        notice = QLabel("조건을 신중히 선택해주세요. '전체 적용'은 이미 입력된 메타데이터도 덮어쓸 수 있습니다.")
        notice.setWordWrap(True)
        notice.setStyleSheet("color:#E6B9C8; font-size:11px;")
        layout.addWidget(notice)
        return card

    def create_action_section(self) -> QWidget:
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        title = QLabel("일괄 적용 작업")
        title.setStyleSheet("font-size:14px; font-weight:bold; color:#F3C7D3;")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self._btn_pixiv_card = self._make_action_button(
            PIXIV_META_LABEL,
            "Pixiv API를 통해 작품 정보를 일괄적으로 조회하여 입력합니다.",
            accent=False,
        )
        self._btn_pixiv_card.clicked.connect(self.on_pixiv_enrich_clicked)
        grid.addWidget(self._btn_pixiv_card, 0, 0)

        self._btn_xmp_card = self._make_action_button(
            "XMP 데이터 입력",
            "XMP / JSON 측면파일을 읽어 메타데이터를 일괄 입력합니다.",
            accent=False,
        )
        self._btn_xmp_card.clicked.connect(self.on_xmp_enrich_clicked)
        grid.addWidget(self._btn_xmp_card, 0, 1)

        self._btn_bulk_card = self._make_action_button(
            "일괄 입력 (모두 적용)",
            "Pixiv + XMP 데이터를 순차적으로 일괄 입력합니다.",
            accent=True,
        )
        self._btn_bulk_card.clicked.connect(self.on_bulk_enrich_clicked)
        grid.addWidget(self._btn_bulk_card, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        outer.addLayout(grid)
        return wrapper

    def create_warning_box(self) -> QWidget:
        box = QFrame()
        box.setStyleSheet(
            "QFrame {"
            " background:#2F1B16;"
            " border:1px solid #A66A2A;"
            " border-radius:12px;"
            "}"
        )
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        icon = QLabel("⚠")
        icon.setStyleSheet("font-size:16px; color:#F0B45F; font-weight:bold;")
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel("대량의 파일을 처리하므로 시간이 오래 걸릴 수 있습니다. (수백~수천 개 이상)")
        text.setWordWrap(True)
        text.setStyleSheet("color:#F7D9A8; font-size:12px;")
        layout.addWidget(text, 1)
        return box

    def create_status_summary_section(self) -> QWidget:
        card = self._make_card_frame()
        layout = QVBoxLayout(card)
        layout.setSpacing(10)

        title = QLabel("현재 보강 대상 상태")
        title.setStyleSheet("font-size:14px; font-weight:bold; color:#F3C7D3;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        statuses = [
            ("metadata_missing", "파일 내 AruArchive 메타데이터가 없는 상태"),
            ("metadata_write_failed", "메타데이터 기록 중 실패한 상태"),
            ("xmp_write_failed", "XMP 기록만 실패한 상태"),
            ("json_only", "JSON만 입력된 상태"),
            ("source_unavailable", "외부 원본에서 조회할 수 없는 상태"),
            ("full", "메타데이터가 모두 입력된 상태"),
            ("pending", "아직 메타데이터 처리가 시작되지 않은 상태"),
        ]
        for index, (status_key, tooltip) in enumerate(statuses):
            card_widget, value_lbl = self._make_status_card(status_key, tooltip)
            self._status_cards[status_key] = value_lbl
            grid.addWidget(card_widget, index // 3, index % 3)

        layout.addLayout(grid)
        return card

    def get_selected_enrich_scope(self) -> str:
        return self._selected_scope

    def on_pixiv_enrich_clicked(self) -> None:
        scope = self.get_selected_enrich_scope()
        if scope == "all":
            self._confirm_and_start_pixiv_all()
        else:
            self._start_pixiv_enrich(mode="missing_only")

    def on_xmp_enrich_clicked(self) -> None:
        self._start_local_import(mode=self.get_selected_enrich_scope())

    def on_bulk_enrich_clicked(self) -> None:
        scope = self.get_selected_enrich_scope()
        self._pending_bulk_followup = scope
        if scope == "all":
            if not self._confirm_pixiv_all():
                self._pending_bulk_followup = None
                return
            self._start_pixiv_enrich(mode="all_pixiv")
        else:
            self._start_pixiv_enrich(mode="missing_only")

    def refresh(self) -> None:
        from core.workflow_summary import build_workflow_file_status_summary
        try:
            conn = self._conn_factory()
            fs = build_workflow_file_status_summary(conn)
            conn.close()
        except Exception:
            return
        self._refresh_status_cards(fs)

    def _on_enrich_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.enrich_modern")
        self._enrich_thread = None
        self._set_actions_enabled(True)
        self._progress.hide()
        self._progress_lbl.setText(
            f"Pixiv 데이터 입력 완료 — 성공: {result['success']}, 실패: {result['failed']}, 스킵: {result['skipped']}"
        )
        if self._pending_bulk_followup:
            followup_mode = self._pending_bulk_followup
            self._pending_bulk_followup = None
            self._start_local_import(mode=followup_mode)
            return
        self._hide_loading()
        _log_phase("postprocess.start", 0.0, op="wizard.enrich_modern")
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.enrich_modern")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.enrich_modern")

    def _on_local_import_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.local_import_modern")
        self._local_import_thread = None
        self._set_actions_enabled(True)
        self._progress.hide()
        self._progress_lbl.setText(
            f"XMP 데이터 입력 완료 — 전체: {result.get('total', 0)}, 성공: {result['success']}, 실패: {result['failed']}, 스킵: {result['skipped']}"
        )
        _log_phase("postprocess.start", 0.0, op="wizard.local_import_modern")
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.local_import_modern")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.local_import_modern")

        self._hide_loading()

    def _make_card_frame(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame {"
            " background:#24121A;"
            " border:1px solid #6B3447;"
            " border-radius:14px;"
            "}"
            "QRadioButton { color:#F9EAF0; spacing:8px; font-size:13px; font-weight:600; }"
            "QRadioButton::indicator { width:14px; height:14px; }"
            "QRadioButton::indicator:unchecked {"
            " border:1px solid #C97E97;"
            " border-radius:7px;"
            " background:#140B0F;"
            "}"
            "QRadioButton::indicator:checked {"
            " border:1px solid #F2B3C8;"
            " border-radius:7px;"
            " background:#D96F8D;"
            "}"
        )
        return frame

    def _make_hint_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color:#D6B9C5; font-size:11px; padding-left:22px;")
        return label

    def _make_action_button(self, title: str, description: str, *, accent: bool) -> QPushButton:
        btn = QPushButton(f"{title}\n{description}")
        btn.setToolTip(description)
        border = "#C36381"
        hover = "#4A2230"
        pressed = "#3A1823"
        bg = "#2B151D"
        text = "#FFF3F7"
        disabled_bg = "#1B1015"
        disabled_border = "#4C2632"
        disabled_text = "#8F6874"
        if accent:
            border = "#F0B45F"
            hover = "#53311E"
            pressed = "#432618"
            bg = "#352018"
            text = "#FFF1DD"
            disabled_bg = "#21150F"
            disabled_border = "#6D4B29"
            disabled_text = "#A98559"
            btn.setObjectName("step4BulkActionButton")
        else:
            btn.setObjectName("step4ActionButton")
        btn.setMinimumHeight(108)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            f" background:{bg};"
            f" color:{text};"
            f" border:1px solid {border};"
            " border-radius:16px;"
            " padding:16px 18px;"
            " text-align:left;"
            " font-size:13px;"
            " font-weight:700;"
            " line-height:1.45;"
            "}"
            f"QPushButton:hover {{ background:{hover}; border-color:#F3B7C8; }}"
            f"QPushButton:pressed {{ background:{pressed}; border-color:#FFD0DD; padding-top:17px; padding-bottom:15px; }}"
            "QPushButton:focus { outline:none; }"
            f"QPushButton:disabled {{ color:{disabled_text}; border:1px solid {disabled_border}; background:{disabled_bg}; }}"
            "QPushButton#step4BulkActionButton { border:2px dashed #F0B45F; }"
            "QPushButton#step4BulkActionButton:hover { border-color:#FFD18D; }"
            "QPushButton#step4BulkActionButton:pressed { border-color:#FFE0AE; }"
        )
        return btn

    def _make_status_card(self, status_key: str, tooltip: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setToolTip(tooltip)
        card.setStyleSheet(
            "QFrame { background:#1B0F15; border:1px solid #4E2432; border-radius:12px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        title = QLabel(status_key)
        title.setStyleSheet("color:#DAB2C0; font-size:11px; font-weight:bold;")
        value = QLabel("0")
        value.setStyleSheet("color:#F7E8EC; font-size:20px; font-weight:bold;")
        layout.addWidget(title)
        layout.addWidget(value)
        return card, value

    def _refresh_status_cards(self, summary: dict) -> None:
        counts = summary.get("metadata_status_counts", {}) or {}
        for status_key, value_lbl in self._status_cards.items():
            value_lbl.setText(str(counts.get(status_key, 0)))

    def _set_selected_scope(self, scope: str) -> None:
        self._selected_scope = scope

    def _confirm_and_start_pixiv_all(self) -> None:
        if self._confirm_pixiv_all():
            self._start_pixiv_enrich(mode="all_pixiv")

    def _confirm_pixiv_all(self) -> bool:
        if self._enrich_thread and self._enrich_thread.isRunning():
            return False
        try:
            conn = self._conn_factory()
            try:
                from core.metadata_enricher import build_enrichment_queue
                count = len(build_enrichment_queue(conn, mode="all_pixiv"))
            finally:
                conn.close()
        except Exception as exc:
            self.log_msg.emit(f"[WARN] 전체 보강 대상 계산 실패: {exc}")
            return False

        if count == 0:
            QMessageBox.information(self, "전체 적용", "Pixiv 전체 적용 대상이 없습니다.")
            return False

        reply = QMessageBox.question(
            self,
            "전체 적용 확인",
            "전체 적용은 이미 입력된 메타데이터도 다시 조회해 덮어쓸 수 있습니다.\n"
            f"Pixiv 기준 처리 대상: {count}건\n\n계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _start_pixiv_enrich(self, *, mode: str) -> None:
        if self._enrich_thread and self._enrich_thread.isRunning():
            return
        db_path = self._db_path()
        from core.exiftool_resolver import resolve_exiftool_path
        exiftool = resolve_exiftool_path(self._config())
        self._set_actions_enabled(False)
        self._progress.show()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_lbl.setText("Pixiv 데이터 입력을 시작합니다…")
        self._show_loading(
            "Step 4: 메타데이터 보강",
            "Pixiv 데이터를 조회해 메타데이터를 입력하는 중입니다…",
            detail="Pixiv API 응답과 파일 수에 따라 시간이 조금 걸릴 수 있습니다.",
            total=1,
            current=0,
        )
        self._enrich_thread = _EnrichThread(db_path, exiftool, self, mode=mode)
        self._enrich_thread.log_msg.connect(self.log_msg)
        self._enrich_thread.log_msg.connect(self._mirror_loading_log)
        self._enrich_thread.progress.connect(self._on_pixiv_progress)
        self._enrich_thread.done.connect(self._on_enrich_done)
        self._enrich_thread.start()

    def _start_local_import(self, *, mode: str) -> None:
        if self._local_import_thread and self._local_import_thread.isRunning():
            return
        cfg = self._config()
        self._set_actions_enabled(False)
        self._progress.show()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_lbl.setText("XMP / JSON 측면파일 메타데이터를 읽는 중입니다…")
        self._show_loading(
            "Step 4: 메타데이터 보강",
            "XMP / JSON 측면파일에서 메타데이터를 읽는 중입니다…",
            detail="기존 파일 메타데이터를 다시 분석하고 있습니다.",
            total=1,
            current=0,
        )
        self._local_import_thread = _LocalMetadataImportThread(
            self._db_path(),
            cfg.get("data_dir", ""),
            cfg.get("managed_dir", ""),
            self,
            mode=mode,
        )
        self._local_import_thread.log_msg.connect(self.log_msg)
        self._local_import_thread.log_msg.connect(self._mirror_loading_log)
        self._local_import_thread.progress.connect(self._on_local_import_progress)
        self._local_import_thread.done.connect(self._on_local_import_done)
        self._local_import_thread.start()

    def _on_pixiv_progress(self, done: int, total: int) -> None:
        total = max(total, 1)
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"Pixiv 데이터 입력 진행 중… {done}/{total}")

    def _on_local_import_progress(self, done: int, total: int, group_id: str) -> None:
        total = max(total, 1)
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"XMP 데이터 입력 진행 중… {done}/{total} ({group_id[:8]}…)")

    def _on_enrich_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.enrich_modern2")
        self._enrich_thread = None
        self._set_actions_enabled(True)
        self._progress.hide()
        self._progress_lbl.setText(
            f"Pixiv 보강 완료 — 성공: {result['success']}, 실패: {result['failed']}, 건너뜀: {result['skipped']}"
        )
        _log_phase("postprocess.start", 0.0, op="wizard.enrich_modern2")
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.enrich_modern2")
        if self._pending_bulk_followup:
            followup_mode = self._pending_bulk_followup
            self._pending_bulk_followup = None
            self._start_local_import(mode=followup_mode)
            _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.enrich_modern2")
            return
        self._hide_loading()
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.enrich_modern2")

    def _on_local_import_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.local_import_modern2")
        self._local_import_thread = None
        self._set_actions_enabled(True)
        self._progress.hide()
        self._progress_lbl.setText(
            f"XMP 입력 완료 — 전체: {result.get('total', 0)}, 성공: {result['success']}, 실패: {result['failed']}, 건너뜀: {result['skipped']}"
        )
        self._hide_loading()
        _log_phase("postprocess.start", 0.0, op="wizard.local_import_modern2")
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.local_import_modern2")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.local_import_modern2")

    def _on_pixiv_progress(self, done: int, total: int) -> None:
        total = max(total, 1)
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"Pixiv 데이터 입력 진행 중… {done}/{total}")
        self._update_loading(
            message="Pixiv 데이터 입력 진행 중…",
            current=done,
            total=total,
        )

    def _on_local_import_progress(self, done: int, total: int, group_id: str) -> None:
        total = max(total, 1)
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"XMP 데이터 입력 진행 중… {done}/{total} ({group_id[:8]}…)")
        self._update_loading(
            message="XMP 데이터 입력 진행 중…",
            detail=f"{group_id[:8]}…",
            current=done,
            total=total,
        )

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._btn_pixiv_card.setEnabled(enabled)
        self._btn_xmp_card.setEnabled(enabled)
        self._btn_bulk_card.setEnabled(enabled)


def _apply_level_to_cfg(level: str, cls_cfg: dict) -> None:
    """classification_level 문자열을 기존 분류 플래그에 매핑한다.

    series_only:       시리즈 폴더만 (_uncategorized 포함)
    series_character:  기존 동작 유지 (default)
    tag:               미구현 — series_character로 fallback
    """
    if level == "series_only":
        cls_cfg["enable_series_character"] = False
        cls_cfg["enable_series_uncategorized"] = True
        cls_cfg["enable_character_without_series"] = False
    # series_character / tag / 기타: 기본값 유지 — config.json의 사용자 설정 보존


class _Step5ClassifyLevel(_StepPanel):
    """Step 5 — 분류 기준 선택.

    이전 사전 정규화 패널은 후보 태그 / 웹 사전 / 사전 내보내기 기능을
    가졌으나, 동일 기능이 Top Menu '정규화'에 모두 존재하므로 Wizard에서는
    분류 기준 선택 UI로 교체한다.

    상단: 경량 사전 상태 요약 (pending 후보 N건) + 정규화 도구 열기 버튼
    하단: 분류 기준 RadioButton 그룹
    """

    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("분류 기준 선택", bold=True))
        layout.addWidget(_h_sep())

        # 상단 — 경량 사전 상태 요약
        self._dict_summary_lbl = QLabel("사전 상태: 로드 중…")
        self._dict_summary_lbl.setStyleSheet("color:#8F8890; font-size:12px;")
        layout.addWidget(self._dict_summary_lbl)

        btn_open_dict_tools = QPushButton("정규화 도구 열기 (Top Menu)")
        btn_open_dict_tools.setObjectName("btn_open_dict_tools")
        btn_open_dict_tools.setToolTip(
            "Top Menu의 '정규화' 메뉴에 후보 태그 / 웹 사전 / 사전 내보내기 기능이 있습니다."
        )
        btn_open_dict_tools.clicked.connect(self._on_open_dict_tools)
        layout.addWidget(btn_open_dict_tools)

        layout.addWidget(_h_sep())

        # 하단 — 분류 기준 RadioButton
        layout.addWidget(_label("분류 기준", bold=True))

        self._radio_group = QButtonGroup(self)

        self._radio_series_char = QRadioButton("시리즈 + 캐릭터 폴더 (권장)")
        self._radio_series_char.setToolTip(
            "BySeries/{series}/{character}/ 또는 ByCharacter/{character}/ 형태로 분류"
        )
        self._radio_group.addButton(self._radio_series_char, 0)
        layout.addWidget(self._radio_series_char)

        self._radio_series_only = QRadioButton("시리즈 폴더만 (_uncategorized 포함)")
        self._radio_series_only.setToolTip(
            "BySeries/{series}/_uncategorized/ 형태로만 분류"
        )
        self._radio_group.addButton(self._radio_series_only, 1)
        layout.addWidget(self._radio_series_only)

        self._radio_tag = QRadioButton("개별 태그별 (추후 지원 예정)")
        self._radio_tag.setEnabled(False)
        self._radio_tag.setToolTip("아직 구현되지 않았습니다.")
        self._radio_group.addButton(self._radio_tag, 2)
        layout.addWidget(self._radio_tag)

        # config에서 현재 값 읽어 적용
        self._restore_from_config()

        # 변경 시 config + 영구 저장
        self._radio_series_char.toggled.connect(self._on_level_changed)
        self._radio_series_only.toggled.connect(self._on_level_changed)

        layout.addStretch()

    def _on_open_dict_tools(self) -> None:
        QMessageBox.information(
            self, "정규화 도구",
            "Top Menu의 '정규화' 메뉴에서 후보 태그 / 웹 사전 / 사전 내보내기 "
            "기능을 사용할 수 있습니다.\n\n"
            "필요 시 작업 마법사를 닫지 않고 메뉴에서 작업 후 돌아올 수 있습니다.",
        )

    def _restore_from_config(self) -> None:
        cfg = self._config()
        cls_cfg = cfg.setdefault("classification", {})
        level = cls_cfg.get("classification_level", "series_character")
        if level == "series_only":
            self._radio_series_only.setChecked(True)
        else:
            self._radio_series_char.setChecked(True)

    def _on_level_changed(self) -> None:
        if self._radio_series_only.isChecked():
            level = "series_only"
        else:
            level = "series_character"
        cfg = self._config()
        cfg.setdefault("classification", {})["classification_level"] = level
        try:
            from core.config_manager import save_config
            config_path = getattr(self._wizard, "_config_path", "config.json")
            save_config(cfg, config_path)
        except Exception:
            pass

        # Step 7 가 보유한 _batch_preview 는 변경 전 분류 기준으로 생성됐으므로
        # stale 임을 표시한다. preview/destination 자체는 변경하지 않음 — 사용자가
        # 미리보기를 다시 누르면 dirty 가 자동 해제된다.
        self._notify_step7_preview_stale("분류 기준이 변경되었습니다.")

    def _notify_step7_preview_stale(self, reason: str) -> None:
        """wizard 의 _Step7Preview 패널을 찾아 stale 로 마킹한다.

        Step 5 → Step 7 직접 reference 가 없으므로 wizard._panels 에서 타입으로
        찾는다. Step 7 가 아직 만들어지지 않았거나 helper 가 없으면 silently
        no-op — UI 회귀 위험을 줄인다.
        """
        wizard = getattr(self, "_wizard", None)
        panels = getattr(wizard, "_panels", None) if wizard is not None else None
        if not panels:
            return
        for panel in panels:
            if isinstance(panel, _Step7Preview):
                marker = getattr(panel, "mark_preview_dirty", None)
                if callable(marker):
                    try:
                        marker(reason)
                    except Exception:
                        pass
                break

    def refresh(self) -> None:
        try:
            from core.workflow_summary import build_dictionary_status_summary
            conn = self._conn_factory()
            try:
                ds = build_dictionary_status_summary(conn)
            finally:
                conn.close()
            pending = ds.get("pending_candidates", 0) if isinstance(ds, dict) else 0
            self._dict_summary_lbl.setText(f"사전 상태: 검토 대기 후보 {pending}건")
        except Exception:
            self._dict_summary_lbl.setText("사전 상태: 정보를 가져올 수 없습니다.")


# ── Step 6: Tag Reclassification ────────────────────────────────────────────

class _Step6Retag(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("태그 다시 분석", bold=True))
        layout.addWidget(_h_sep())

        layout.addWidget(QLabel(
            "⚠ 사전(aliases) 변경 후 태그 재분석을 하지 않으면\n"
            "  분류 결과(series_tags / character_tags)가 갱신되지 않습니다."
        ))

        btn_row = QHBoxLayout()
        self._btn_retag = QPushButton("🏷 전체 태그 재분석")
        self._btn_retag.setToolTip(
            "현재 태그와 사용자 보정값을 바탕으로 분류 결과를 다시 계산합니다."
        )
        self._btn_retag.clicked.connect(self._on_retag_all)
        btn_row.addWidget(self._btn_retag)
        self._btn_refresh = QPushButton("🔄 새로고침")
        self._btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(self._btn_refresh)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        summary_row = QHBoxLayout()
        self._lbl_total    = QLabel("전체: -")
        self._lbl_done     = QLabel("완료: -")
        self._lbl_failed   = QLabel("실패: -")
        self._lbl_changed  = QLabel("변경 있음: -")
        self._lbl_nochange = QLabel("변경 없음: -")
        for lbl in (self._lbl_total, self._lbl_done, self._lbl_failed,
                    self._lbl_changed, self._lbl_nochange):
            summary_row.addWidget(lbl)
        summary_row.addStretch()
        layout.addLayout(summary_row)

        self._result_grid = QTableWidget(0, 8)
        self._result_grid.setHorizontalHeaderLabels([
            "파일명", "제목", "이전 시리즈", "이전 캐릭터",
            "새 시리즈", "새 캐릭터", "상태", "비고",
        ])
        self._result_grid.horizontalHeader().setStretchLastSection(True)
        self._result_grid.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._result_grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._result_grid.setAlternatingRowColors(True)
        self._result_grid.setStyleSheet(
            "QTableWidget { background: #1A0F14; color: #D8AEBB; "
            "alternate-background-color: #211018; border: 1px solid #4A2030; }"
        )
        layout.addWidget(self._result_grid, 1)

        self._empty_lbl = QLabel("재분석 결과가 없습니다. [전체 태그 재분석]을 실행하세요.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_lbl)

        self._retag_thread: Optional[_RetagThread] = None

    def refresh(self) -> None:
        try:
            conn = self._conn_factory()
            total = conn.execute("SELECT COUNT(*) FROM artwork_groups").fetchone()[0]
            conn.close()
            self._lbl_total.setText(f"전체: {total}")
        except Exception:
            pass

    def _on_retag_all(self) -> None:
        if self._retag_thread and self._retag_thread.isRunning():
            return
        self._btn_retag.setEnabled(False)
        self._btn_retag.setText("재분류 중…")
        self._show_loading(
            "Step 6: 태그 재분류",
            "전체 태그를 다시 분석하고 분류 결과를 갱신하는 중입니다…",
            detail="작품 수가 많으면 시간이 걸릴 수 있습니다.",
            total=None,
        )
        self._retag_thread = _RetagThread(self._db_path(), self)
        self._retag_thread.log_msg.connect(self.log_msg)
        self._retag_thread.log_msg.connect(self._mirror_loading_log)
        self._retag_thread.done.connect(self._on_retag_done)
        self._retag_thread.start()

    def _on_retag_done(self, results: list) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.retag")
        self._hide_loading()
        self._btn_retag.setEnabled(True)
        self._btn_retag.setText("🏷 전체 태그 재분석")
        _log_phase("postprocess.start", 0.0, op="wizard.retag")
        self._populate_result_grid(results)
        self.refresh()
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.retag")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.retag")

    def _populate_result_grid(self, results: list) -> None:
        total   = len(results)
        errors  = sum(1 for r in results if r.get("status") == "오류")
        changed = sum(1 for r in results if r.get("changed"))

        self._lbl_total.setText(f"전체: {total}")
        self._lbl_done.setText(f"완료: {total - errors}")
        self._lbl_failed.setText(f"실패: {errors}")
        self._lbl_changed.setText(f"변경 있음: {changed}")
        self._lbl_nochange.setText(f"변경 없음: {total - errors - changed}")

        self._result_grid.setRowCount(0)
        has_rows = total > 0
        self._empty_lbl.setVisible(not has_rows)
        self._result_grid.setVisible(has_rows)

        for r in results:
            row = self._result_grid.rowCount()
            self._result_grid.insertRow(row)
            for col, val in enumerate([
                r.get("filename", ""),
                r.get("title", ""),
                r.get("before_series", ""),
                r.get("before_character", ""),
                r.get("after_series", ""),
                r.get("after_character", ""),
                r.get("status", ""),
                r.get("note", ""),
            ]):
                self._result_grid.setItem(row, col, QTableWidgetItem(val))


# ── Step 7: Classification Preview ──────────────────────────────────────────

def _is_preview_item_needs_review(item: dict) -> bool:
    """preview_item dict에서 '확인 필요' 여부를 판정한다.

    True 조건 (OR):
    - classification_info.classification_reason 이 분류 불완전을 나타내는 값
      ("series_detected_but_character_missing", "series_and_character_missing")
    - destinations 중 하나라도 used_fallback=True

    UI에서만 사용되는 표시 판정이며 DB/core 로직을 변경하지 않는다.
    """
    ci = item.get("classification_info") or {}
    reason = ci.get("classification_reason", "")
    if reason in (
        "series_detected_but_character_missing",
        "series_and_character_missing",
    ):
        return True
    for dest in item.get("destinations", []):
        if dest.get("used_fallback"):
            return True
    return False


def _is_preview_item_manual_override(item: dict) -> bool:
    """preview_item dict에서 manual override 적용 여부를 판정한다.

    True 조건: destinations 중 하나라도
    - override_note == "manual_override"  (apply_override_to_preview_item 마커)
    - rule_type == "manual_override"
    """
    for dest in item.get("destinations", []):
        if dest.get("override_note") == "manual_override":
            return True
        if dest.get("rule_type") == "manual_override":
            return True
    return False


# 분류 규칙 코드 → 사용자 표시 라벨.
# 내부 rule code (PreviewItem.destinations[i].rule_type) 는 절대 변경하지 않는다.
# preview table 의 cell 텍스트와 tooltip 표시에만 사용한다. execute / undo /
# preview=execute 매칭은 rule code 기반이므로 영향 없음.
_RULE_DISPLAY: dict[str, str] = {
    "author_fallback":      "작가명 분류",
    "series_character":     "캐릭터 분류",
    "series_uncategorized": "시리즈 미식별",
    "manual_override":      "수동 분류",
    "series":               "시리즈 분류",
    "character":            "캐릭터 단독 분류",
    "author":               "작가명 분류",
    "by_tag":               "태그 분류",
}


def _format_preview_rule(rule: str) -> str:
    """rule code 를 사용자에게 보일 한글 라벨로 변환.

    매핑에 없으면 "기타" 로 폴백한다 (UI 표시용 기본값).
    빈 값/None 도 "기타" 로 처리해 빈 셀이 노출되지 않도록 한다.
    """
    if not rule:
        return "기타"
    return _RULE_DISPLAY.get(rule, "기타")


def _format_multi_destination_filename(filename: str, dest_idx: int, total: int) -> str:
    """multi-destination row 의 파일명 표시 텍스트.

    같은 PreviewItem 이 destinations 를 여러 개 가질 때, 사용자가 같은 파일명이
    여러 row 로 보이는 것을 중복 버그로 오해하지 않도록 ``· 대상 i/N`` suffix 를
    파일명 셀에 추가한다. total ≤ 1 이면 suffix 없이 원본 파일명만 반환.

    데이터(``source_path`` / ``destinations``) 자체는 변경하지 않으며, 이 함수는
    cell 표시용 string 생성에만 사용된다.
    """
    if total <= 1:
        return filename
    return f"{filename}  ·  대상 {dest_idx}/{total}"


def _multi_destination_tooltip_lines(
    dest_idx: int, total: int, all_destinations: list[dict]
) -> list[str]:
    """multi-destination 안내 tooltip 의 추가 라인.

    total ≤ 1 이면 빈 list 를 반환해 caller 가 그냥 base tooltip 만 표시하게
    한다. 그렇지 않으면 ``이 파일은 N개 대상 경로로 분류됩니다.`` 안내 +
    현재 dest 위치 + (가능하면) 전체 destination path 목록 5개까지를
    bullet 으로 첨부한다.
    """
    if total <= 1:
        return []
    lines: list[str] = [
        "",
        f"이 파일은 {total}개 대상 경로로 분류됩니다.",
        f"현재 행: 대상 {dest_idx}/{total}",
    ]
    # 전체 destination 목록 — 너무 길면 잘라낸다.
    paths = [d.get("dest_path", "") for d in all_destinations if d.get("dest_path")]
    if paths:
        lines.append("전체 대상:")
        for i, p in enumerate(paths[:5], 1):
            lines.append(f"  {i}. {p}")
        if len(paths) > 5:
            lines.append(f"  … 외 {len(paths) - 5}개 더")
    return lines


class _Step7Preview(_StepPanel):
    preview_ready = Signal(dict)   # batch_preview 전달

    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        self._batch_preview: Optional[dict] = None
        self._preview_rows: list[dict] = []   # {source_path, group_id, title} per table row
        self._preview_items: dict[str, dict] = {}  # group_id → preview item (override 재참조)
        self._thumb_cache = PreviewThumbnailCache(max_items=200)
        self._filter_mode: str = "all"  # "all" | "needs_review" | "manual_override"

        # preview stale 상태 추적 — Step 5 분류 기준 변경 등이 발생했을 때
        # 기존 _batch_preview 가 더 이상 현재 설정을 반영하지 않음을 표시한다.
        # destination/classification 로직 자체는 변경되지 않으며, 사용자가
        # 미리보기를 다시 생성하면 dirty 상태는 해제된다.
        self._preview_dirty_reason: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(_label("분류 미리보기", bold=True))
        layout.addWidget(_h_sep())

        # Stale notice — 분류 기준 / 사전 등 외부 변경 후 기존 preview 가 stale
        # 임을 사용자에게 알리는 안내. 초기에는 hidden, mark_preview_dirty 로
        # 표시 / clear_preview_dirty 로 숨김.
        self._stale_notice_lbl = QLabel("")
        self._stale_notice_lbl.setObjectName("step7StaleNotice")
        self._stale_notice_lbl.setWordWrap(True)
        self._stale_notice_lbl.setStyleSheet(
            "color: #FFB070; background: #2B1A14; "
            "border: 1px solid #6A3A26; border-radius: 4px; "
            "padding: 6px 10px; font-size: 11px;"
        )
        self._stale_notice_lbl.setVisible(False)
        layout.addWidget(self._stale_notice_lbl)

        # author_fallback 안내 — 항상 표시. 분류 실패 시 작가명 기준으로 자동
        # 분류된다는 정책을 사용자에게 알린다. 라벨 자체는 표시 전용이며
        # classification 로직에는 영향 없음.
        self._author_fallback_notice_lbl = QLabel(
            "원본 태그가 부족하거나 시리즈/캐릭터를 식별하지 못한 경우 "
            "작가명 기준으로 분류됩니다. 필요한 항목은 미리보기에서 수동으로 수정하세요.\n"
            "여러 캐릭터가 감지된 이미지는 대상 경로별로 여러 줄 표시될 수 있습니다."
        )
        self._author_fallback_notice_lbl.setObjectName("step7AuthorFallbackNotice")
        self._author_fallback_notice_lbl.setWordWrap(True)
        self._author_fallback_notice_lbl.setStyleSheet(
            "color: #C8B0A8; background: #221814; "
            "border: 1px solid #4A2A20; border-radius: 4px; "
            "padding: 6px 10px; font-size: 11px;"
        )
        layout.addWidget(self._author_fallback_notice_lbl)

        # 설정 행
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("대상:"))
        self._scope_combo = QComboBox()
        for val, label in _SCOPE_OPTIONS:
            self._scope_combo.addItem(label, val)
        opt_row.addWidget(self._scope_combo)

        opt_row.addSpacing(12)
        opt_row.addWidget(QLabel("폴더명 언어:"))
        self._locale_combo = QComboBox()
        for val, label in _LOCALE_OPTIONS:
            self._locale_combo.addItem(label, val)
        idx = self._locale_combo.findData(
            self._config().get("classification", {}).get("folder_locale", "ko")
        )
        if idx >= 0:
            self._locale_combo.setCurrentIndex(idx)
        opt_row.addWidget(self._locale_combo)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # 컴팩트 요약 레이블
        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        sf = QHBoxLayout(summary_frame)
        sf.setContentsMargins(6, 4, 6, 4)
        self._s_total     = QLabel("대상 작품: -")
        self._s_copies    = QLabel("예상 복사본: -")
        self._s_bytes     = QLabel("예상 용량: -")
        self._s_conflicts = QLabel("충돌: -")
        self._s_fallbacks = QLabel("폴백: -")
        self._risk_lbl    = QLabel("위험도: -")
        for lbl in (self._s_total, self._s_copies, self._s_bytes,
                    self._s_conflicts, self._s_fallbacks, self._risk_lbl):
            sf.addWidget(lbl)
        sf.addStretch()
        layout.addWidget(summary_frame)

        btn_row = QHBoxLayout()
        self._btn_preview = QPushButton("📋 분류 미리보기 생성")
        self._btn_preview.setToolTip(
            "태그 재분석을 먼저 수행한 뒤, 적용 전 결과를 미리 보여줍니다. "
            "항목 수가 많으면 시간이 걸릴 수 있습니다."
        )
        self._btn_preview.clicked.connect(self._on_preview)
        btn_row.addWidget(self._btn_preview)

        btn_row.addSpacing(16)
        btn_row.addWidget(QLabel("필터:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItem("전체", "all")
        self._filter_combo.addItem("확인 필요", "needs_review")
        self._filter_combo.addItem("수동 보정됨", "manual_override")
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        btn_row.addWidget(self._filter_combo)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 미리보기 테이블 + 썸네일 패널
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self._preview_table = QTableWidget(0, 7)
        # 헤더 라벨 — 데이터 column index 는 그대로 유지하며 (override / filter
        # 로직과 호환), '분류대상' / '사유·경고' 두 컬럼은 setColumnHidden 으로
        # 사용자에게 숨긴다. 시각적 노출 순서는 horizontalHeader().moveSection
        # 으로 [파일명, 제목, 상태, 규칙, 경로] 가 되도록 재배치.
        self._preview_table.setHorizontalHeaderLabels(
            ["파일명", "제목", "분류대상", "규칙", "사유·경고", "경로", "상태"]
        )
        hdr = self._preview_table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._preview_table.setColumnWidth(0, 130)
        self._preview_table.setColumnWidth(1, 160)
        self._preview_table.setColumnWidth(2, 70)
        self._preview_table.setColumnWidth(3, 110)
        self._preview_table.setColumnWidth(4, 130)
        self._preview_table.setColumnWidth(6, 90)
        # 분류대상 / 사유·경고 는 사용자에게 숨김. 데이터는 보존되어 tooltip 및
        # 내부 필터 / override 로직에서 그대로 사용된다.
        self._preview_table.setColumnHidden(2, True)
        self._preview_table.setColumnHidden(4, True)
        # 시각 순서 재배치: [파일명, 제목, 상태, 규칙, 경로].
        # 데이터 logical index 는 변경되지 않는다 — visualIndex 만 이동.
        # 상태 (logical 6) 를 visual 2 위치로, 규칙 (logical 3) 을 visual 3 위치로,
        # 경로 (logical 5) 를 visual 4 위치로 이동.
        hdr.moveSection(hdr.visualIndex(6), 2)
        hdr.moveSection(hdr.visualIndex(3), 3)
        hdr.moveSection(hdr.visualIndex(5), 4)
        # minimumWidth 를 줄여 splitter 가 우측 thumb 패널을 더 넉넉히 줄 수 있게 한다.
        # 기본 column 합 ≈ 690 + stretch(col5). 700 으로 두면 stretch column 이
        # 최소 폭으로 압축되어도 다른 column 들은 그대로 표시된다.
        self._preview_table.setMinimumWidth(700)
        self._preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.setStyleSheet(
            "QTableWidget { background: #1A0F14; color: #D8AEBB; "
            "alternate-background-color: #211018; border: 1px solid #4A2030; }"
        )
        self._preview_table.currentItemChanged.connect(
            lambda cur, _prev: self._on_preview_row_changed(
                self._preview_table.row(cur) if cur else -1
            )
        )
        # 우클릭 컨텍스트 메뉴 (수동 분류 지정)
        self._preview_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._preview_table.customContextMenuRequested.connect(
            self._on_preview_context_menu
        )
        splitter.addWidget(self._preview_table)

        thumb_frame = QFrame()
        thumb_frame.setFrameShape(QFrame.Shape.StyledPanel)
        # 우측 패널 최소폭을 키워 이미지/파일명/태그가 모두 표시되도록 한다.
        thumb_frame.setMinimumWidth(220)
        tf = QVBoxLayout(thumb_frame)
        tf.setContentsMargins(6, 6, 6, 6)
        tf.setSpacing(6)
        self._thumb_lbl = QLabel("썸네일")
        self._thumb_lbl.setFixedSize(160, 160)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setStyleSheet("border: 1px solid #4A2030; background: #120A0E;")
        tf.addWidget(self._thumb_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._thumb_name_lbl = QLabel("")
        self._thumb_name_lbl.setWordWrap(True)
        self._thumb_name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tf.addWidget(self._thumb_name_lbl)

        # 태그 표시 영역 — fixed-height scroll area 로 layout 안정성 확보.
        # 태그가 많아도 우측 패널 height 가 무한정 커지지 않는다.
        # 표시 전용 — preview row data / classification result / destination path
        # 어느 것도 변경하지 않는다.
        tags_caption = QLabel("태그")
        tags_caption.setStyleSheet("color: #8F6874; font-size: 10px; padding-left: 2px;")
        tf.addWidget(tags_caption)

        self._thumb_tags_lbl = QLabel("태그 없음")
        self._thumb_tags_lbl.setWordWrap(True)
        self._thumb_tags_lbl.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._thumb_tags_lbl.setStyleSheet(
            "color: #C0A0B0; font-size: 11px; padding: 4px;"
        )
        self._thumb_tags_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._thumb_tags_scroll = QScrollArea()
        self._thumb_tags_scroll.setWidgetResizable(True)
        self._thumb_tags_scroll.setWidget(self._thumb_tags_lbl)
        # 최대 높이 제한 — 태그가 많아도 layout 이 망가지지 않도록 scroll 로 흡수.
        self._thumb_tags_scroll.setMaximumHeight(160)
        self._thumb_tags_scroll.setMinimumHeight(60)
        self._thumb_tags_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #4A2030; background: #1A0F14; }"
        )
        tf.addWidget(self._thumb_tags_scroll)

        tf.addStretch()
        splitter.addWidget(thumb_frame)
        splitter.setSizes([720, 280])

        self._preview_thread: Optional[_PreviewThread] = None

    def refresh(self) -> None:
        if self._batch_preview:
            self._show_preview_summary(self._batch_preview)

    def _build_config_override(self) -> dict:
        cfg  = dict(self._config())
        cls  = dict(cfg.get("classification", {}))
        cls["folder_locale"] = self._locale_combo.currentData() or "canonical"
        # PR A: Step 6를 자동화 — preview 생성 전 retag 자동 실행 플래그
        cls["retag_before_batch_preview"] = True
        # PR A: classification_level을 기존 분류 플래그에 매핑
        _apply_level_to_cfg(cls.get("classification_level", "series_character"), cls)
        cfg["classification"] = cls
        return cfg

    @staticmethod
    def _collect_provider_ids(provider) -> list[str]:
        """Wizard 외부에서 주입된 group ids provider 를 안전하게 호출.

        Provider 가 None / non-callable / 예외 발생 시 빈 list 반환 — preview
        흐름이 끊기지 않도록 한다. ``collect_classifiable_group_ids`` 가 빈 list
        를 받으면 기존 정책대로 candidate 0건으로 처리한다.
        """
        if not callable(provider):
            return []
        try:
            result = provider()
        except Exception:
            return []
        if not result:
            return []
        return list(result)

    def _on_preview(self) -> None:
        if self._preview_thread and self._preview_thread.isRunning():
            return

        # P0 가드: classified_dir 미설정 시 preview thread를 시작하지 않는다.
        # build_classify_preview()가 모든 group에 대해 silently None을 반환해
        # 0건 결과로 보이는 상황을 사전 차단하고 사용자에게 원인을 알린다.
        # 버튼 상태와 _batch_preview는 손대지 않으므로 dirty state / preview≡execute
        # frozen 구조에 영향이 없다.
        classified_dir = (self._config().get("classified_dir") or "").strip()
        if not classified_dir:
            QMessageBox.warning(
                self._wizard,
                "분류 폴더 미설정",
                "분류 미리보기를 만들려면 먼저 Step 1 작업폴더에서 "
                "분류 결과를 저장할 폴더를 지정해야 합니다.",
            )
            return

        self._btn_preview.setEnabled(False)
        self._btn_preview.setText("생성 중…")
        self._batch_preview = None
        cfg     = self._build_config_override()
        db_path = self._db_path()

        from db.database import initialize_database
        from core.batch_classifier import collect_classifiable_group_ids

        try:
            conn     = self._conn_factory()
            scope    = self._scope_combo.currentData() or "all_classifiable"
            # P0 fix: scope='current_filter' / 'selected' 시 wizard 외부에서 주입된
            # provider 를 통해 group ids 를 조회한다. provider 미설정 시 기본값
            # (None → 빈 list) — 기존 all_classifiable 동작은 영향 없음.
            selected_ids = self._collect_provider_ids(
                getattr(self._wizard, "_selected_group_ids_provider", None)
            )
            filter_ids = self._collect_provider_ids(
                getattr(self._wizard, "_current_filter_group_ids_provider", None)
            )
            gathered = collect_classifiable_group_ids(
                conn, scope,
                selected_group_ids=selected_ids,
                current_filter_group_ids=filter_ids,
                classified_dir=cfg.get("classified_dir", ""),
            )
            group_ids = gathered.get("included_group_ids", [])
            conn.close()
        except Exception as exc:
            self._btn_preview.setEnabled(True)
            self._btn_preview.setText("📋 분류 미리보기 생성")
            QMessageBox.critical(self._wizard, "오류", str(exc))
            return

        self._preview_thread = _PreviewThread(
            self._conn_factory, group_ids, cfg, self
        )
        self._preview_thread.log_msg.connect(self.log_msg)
        self._preview_thread.log_msg.connect(self._mirror_loading_log)
        self._preview_thread.done.connect(self._on_preview_done)
        self._show_loading(
            "Step 7: 분류 미리보기",
            "분류 미리보기를 생성하는 중입니다…",
            detail=f"대상 그룹 {len(group_ids)}개를 분석하고 있습니다.",
            total=None,
        )
        self._preview_thread.start()

    def _on_preview_done(self, result: dict) -> None:
        self._hide_loading()
        self._btn_preview.setEnabled(True)
        # 초기 라벨과 동일하게 통일 — preview 완료 후 다시 누를 때 무엇을 분류
        # 미리보는지 명확히 한다.
        self._btn_preview.setText("📋 분류 미리보기 생성")
        # developer: 분류 실패 export 로그 (기본값 OFF, 일반 사용자에게 표시 안 됨)
        if result.get("dev_log_msg"):
            self.log_msg.emit(result["dev_log_msg"])
        # PR A: retag 자동 실행 안내
        self.log_msg.emit("[INFO] Preview 생성 전 자동 태그 재분류가 수행되었습니다.")
        self._batch_preview = result
        self._show_preview_summary(result)
        self.preview_ready.emit(result)
        # 새 preview 가 현재 설정으로 막 생성됐으므로 stale 상태 해제.
        self.clear_preview_dirty()

    # ------------------------------------------------------------------
    # Stale (dirty) state — 분류 기준 / 사전 변경 후 preview 가 현재 설정과
    # 다를 수 있음을 사용자에게 알린다. preview/destination 계산 자체는
    # 변경되지 않으며, 사용자가 미리보기를 다시 생성하면 자동 해제된다.
    # ------------------------------------------------------------------

    def mark_preview_dirty(self, reason: str) -> None:
        """기존 preview 가 stale 임을 표시한다.

        Parameters
        ----------
        reason:
            사용자에게 보여줄 짧은 사유 (예: "분류 기준 변경"). 빈 문자열이면
            기본 안내가 사용된다.

        본 helper 는 destination 또는 preview rows 자체를 변경하지 않는다.
        사용자가 [📋 분류 미리보기 생성] 을 다시 누르면 ``clear_preview_dirty``
        가 자동 호출돼 안내가 사라진다.
        """
        self._preview_dirty_reason = reason or "분류 기준이 변경되었습니다."
        if hasattr(self, "_stale_notice_lbl"):
            self._stale_notice_lbl.setText(
                f"⚠ {self._preview_dirty_reason} "
                "현재 보이는 결과는 이전 설정 기준입니다. "
                "새 결과를 보려면 [📋 분류 미리보기 생성] 을 다시 누르세요."
            )
            self._stale_notice_lbl.setVisible(True)

    def clear_preview_dirty(self) -> None:
        """stale 표시를 해제한다 (preview 재생성 성공 시 자동 호출)."""
        self._preview_dirty_reason = None
        if hasattr(self, "_stale_notice_lbl"):
            self._stale_notice_lbl.setText("")
            self._stale_notice_lbl.setVisible(False)

    def is_preview_dirty(self) -> bool:
        """외부 (테스트 / 다른 패널) 에서 dirty 여부 조회용."""
        return self._preview_dirty_reason is not None

    def _show_preview_summary(self, result: dict) -> None:
        from core.workflow_summary import compute_preview_risk_level
        summary = self._build_preview_summary(result)

        total   = result.get("total_groups", 0)
        copies  = result.get("estimated_copies", 0)
        fbcount = result.get("author_fallback_count", 0) + result.get("series_uncategorized_count", 0)
        self._s_total.setText(f"대상 작품: {total}")
        self._s_copies.setText(f"예상 복사본: {copies}")
        self._s_bytes.setText(f"예상 용량: {_fmt_size(result.get('estimated_bytes', 0))}")
        self._s_conflicts.setText(f"충돌: {summary.get('conflict_count', 0)}")
        self._s_fallbacks.setText(f"폴백: {fbcount}")

        self._populate_preview_table(result.get("previews", []))

        risk = compute_preview_risk_level(summary)
        risk_label = {"low": "낮음", "medium": "보통", "high": "높음"}.get(risk, risk)
        self._risk_lbl.setText(f"위험도: {risk_label}")
        self._risk_lbl.setStyleSheet(_RISK_STYLE.get(risk, ""))

    def _build_preview_summary(self, result: dict) -> dict:
        previews = result.get("previews", [])
        conflict_count = 0
        destination_count = 0
        for preview in previews:
            for dest in preview.get("destinations", []):
                destination_count += 1
                if dest.get("conflict") not in (None, "", "none"):
                    conflict_count += 1
        return {
            "total_groups":          result.get("total_groups", 0),
            "excluded_count":        result.get("excluded_groups", 0),
            "author_fallback_count": result.get("author_fallback_count", 0),
            "conflict_count":        conflict_count,
            "destination_count":     destination_count,
        }

    @staticmethod
    def _collect_preview_tags(preview: Optional[dict]) -> list[str]:
        """preview dict 에 이미 들어 있는 tag-like 값들을 표시용 list 로 합친다.

        새 DB query 없이 build_classify_preview 결과만 활용한다. 출처:
        1. classification_info.candidate_source_tags (raw tags 일부, 분류 실패 시 존재)
        2. fallback_tags (folder localization 이 canonical 로 fallback 한 tag)
        3. inferred_series_evidence[].canonical (character→series 추론 근거)

        모든 출처에서 dedupe + 원본 순서 유지. 표시용 list 만 변경, preview dict
        자체는 미터치.
        """
        if not preview:
            return []
        out: list[str] = []
        seen: set[str] = set()

        def _add(value) -> None:
            if value is None:
                return
            s = str(value).strip()
            if not s or s in seen:
                return
            seen.add(s)
            out.append(s)

        ci = preview.get("classification_info") or {}
        for t in ci.get("candidate_source_tags") or []:
            _add(t)
        for t in preview.get("fallback_tags") or []:
            _add(t)
        for ev in preview.get("inferred_series_evidence") or []:
            if isinstance(ev, dict):
                _add(ev.get("canonical"))

        return out

    def _on_preview_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._preview_rows):
            self._thumb_lbl.clear()
            self._thumb_lbl.setText("썸네일")
            self._thumb_name_lbl.setText("")
            self._thumb_tags_lbl.setText("태그 없음")
            return
        row_data = self._preview_rows[row]
        path = row_data.get("source_path", "")
        px = self._thumb_cache.load(path) if path else None
        if px:
            self._thumb_lbl.setPixmap(px)
        else:
            self._thumb_lbl.clear()
            self._thumb_lbl.setText("미리보기 없음")
        self._thumb_name_lbl.setText(Path(path).name if path else "")

        # 태그 표시 — _preview_items 캐시에서 group_id 로 preview dict 조회.
        # _preview_items 가 없거나 group_id 가 비면 fallback 표시.
        group_id = row_data.get("group_id", "")
        preview_dict = None
        if group_id:
            preview_dict = getattr(self, "_preview_items", {}).get(group_id)
        tags = self._collect_preview_tags(preview_dict)
        if tags:
            # bullet list — 가독성 + scroll 시 줄 단위 식별 용이
            self._thumb_tags_lbl.setText("\n".join(f"• {t}" for t in tags))
        else:
            self._thumb_tags_lbl.setText("태그 없음")

    def _populate_preview_table(self, previews: list[dict]) -> None:
        self._preview_table.setRowCount(0)
        self._preview_rows.clear()
        # preview item 전체를 group_id 키로 인덱싱 (override 적용 시 재참조용)
        self._preview_items: dict[str, dict] = {
            p["group_id"]: p for p in previews if p.get("group_id")
        }

        for preview in previews:
            source_path = preview.get("source_path", "")
            group_id    = preview.get("group_id", "")
            filename    = Path(source_path).name
            title       = preview.get("artwork_title", "")
            ci = preview.get("classification_info") or {}
            reason = ci.get("classification_reason", "")
            ci_warn = (
                "series_uncategorized" if reason == "series_detected_but_character_missing"
                else "author_fallback"  if reason == "series_and_character_missing"
                else ""
            )
            inference_reasons = preview.get("inference_reasons") or []

            # 상태 컬럼 값 결정 (preview 단위)
            item_status, item_status_tip = self._compute_item_status(preview)

            destinations = preview.get("destinations", [])
            total_dests = len(destinations)

            for dest_pos, dest in enumerate(destinations, start=1):
                dest_path = dest.get("dest_path", "")
                rule_type = dest.get("rule_type", "")
                will_copy = dest.get("will_copy", False)

                warn_parts: list[str] = []
                if dest.get("used_fallback"):
                    warn_parts.append("fallback")
                if dest.get("conflict") not in (None, "", "none"):
                    warn_parts.append(str(dest.get("conflict")))
                if ci_warn:
                    warn_parts.append(ci_warn)
                # Read-only 추론 reason 은 destination 별이 아니라 group 별이므로,
                # 같은 group 의 모든 destination row 에 동일하게 표시한다.
                # destination path / 분류 결과 자체는 변경하지 않는다.
                warn_parts.extend(inference_reasons)
                warn_str = ", ".join(warn_parts)

                row = self._preview_table.rowCount()
                self._preview_table.insertRow(row)
                # group_id, source_path 모두 저장 (override 진입 시 필요)
                self._preview_rows.append({
                    "source_path": source_path,
                    "group_id":    group_id,
                    "title":       title,
                })

                rule_display = _format_preview_rule(rule_type)
                filename_cell = _format_multi_destination_filename(
                    filename, dest_pos, total_dests
                )
                multi_lines = _multi_destination_tooltip_lines(
                    dest_pos, total_dests, destinations
                )
                base_tooltip = (
                    f"파일: {filename}\n제목: {title}\n"
                    f"규칙: {rule_display} ({rule_type})\n"
                    f"분류사유·비고: {warn_str}\n"
                    f"분류 경로: {dest_path}"
                ) + ("\n" + "\n".join(multi_lines) if multi_lines else "")
                status_tooltip = item_status_tip + (
                    "\n" + "\n".join(multi_lines) if multi_lines else ""
                )
                col_values = [
                    filename_cell, title,
                    "분류됨" if will_copy else "제외",
                    rule_display, warn_str, dest_path,
                    item_status,
                ]
                for col, val in enumerate(col_values):
                    it = QTableWidgetItem(val)
                    if col == 6:
                        it.setToolTip(status_tooltip)
                    else:
                        it.setToolTip(base_tooltip)
                    self._preview_table.setItem(row, col, it)

        # 필터 재적용 (populate 후 현재 필터 모드 반영)
        self._apply_filter(self._filter_mode)

    # ------------------------------------------------------------------
    # 수동 분류 지정 (우클릭 컨텍스트 메뉴)
    # ------------------------------------------------------------------

    def _on_preview_context_menu(self, pos) -> None:
        """우클릭 위치의 row를 기준으로 컨텍스트 메뉴를 표시한다."""
        from PyQt6.QtWidgets import QMenu
        item = self._preview_table.itemAt(pos)
        if item is None:
            return
        row = self._preview_table.row(item)
        if row < 0 or row >= len(self._preview_rows):
            return

        menu = QMenu(self)
        act_override = menu.addAction("수동 분류 지정")
        act_override.setShortcut("Ctrl+M")
        chosen = menu.exec(self._preview_table.viewport().mapToGlobal(pos))
        if chosen is act_override:
            self._open_manual_override_dialog(row)

    def _open_manual_override_dialog(self, row: int) -> None:
        """선택된 preview row에 대해 ManualClassifyOverrideDialog를 열고 override를 적용한다."""
        from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog
        from core.classification_overrides import (
            apply_override_to_preview_item,
            set_override_for_group,
        )

        row_data  = self._preview_rows[row]
        group_id  = row_data.get("group_id", "")
        if not group_id:
            return

        source_path = row_data.get("source_path", "")
        title       = row_data.get("title", "")
        filename    = Path(source_path).name

        # destinations에서 현재 dest_path 읽기
        dest_path = ""
        rule_type = ""
        tbl_item = self._preview_table.item(row, 5)
        if tbl_item:
            dest_path = tbl_item.text()
        tbl_rule = self._preview_table.item(row, 3)
        if tbl_rule:
            rule_type = tbl_rule.text()

        current_locale = self._locale_combo.currentData() or "canonical"

        group_info = {
            "filename":    filename,
            "title":       title,
            "artist_name": "",
            "raw_tags":    [],
            "rule_type":   rule_type,
            "dest_path":   dest_path,
        }

        try:
            conn = self._conn_factory()
        except Exception as exc:
            QMessageBox.critical(self._wizard, "DB 오류", str(exc))
            return

        artist_name = ""
        raw_tags: list[str] = []
        try:
            row = conn.execute(
                "SELECT artist_name, tags_json FROM artwork_groups WHERE group_id=?",
                (group_id,),
            ).fetchone()
            if row:
                artist_name = (row["artist_name"] or "").strip()
                try:
                    raw_tags = json.loads(row["tags_json"] or "[]")
                except Exception:
                    raw_tags = []
        except Exception:
            raw_tags = []

        if not raw_tags:
            preview_item = self._preview_items.get(group_id) or {}
            ci = preview_item.get("classification_info") or {}
            raw_tags = list(ci.get("candidate_source_tags") or [])

        group_info = {
            "filename":    filename,
            "title":       title,
            "artist_name": artist_name,
            "raw_tags":    raw_tags,
            "rule_type":   rule_type,
            "dest_path":   dest_path,
        }

        dlg = ManualClassifyOverrideDialog(
            group_info=group_info,
            conn=conn,
            current_locale=current_locale,
            parent=self,
        )
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.exec()

        override = dlg.result()
        if override is None:
            conn.close()
            return

        # canonical value만 DB에 저장 (label 저장 금지)
        try:
            set_override_for_group(
                conn,
                group_id=group_id,
                series_canonical=override.get("series_canonical"),
                character_canonical=override.get("character_canonical"),
                folder_locale=override.get("folder_locale") or current_locale,
                reason=override.get("reason"),
            )
        except Exception as exc:
            conn.close()
            QMessageBox.critical(self._wizard, "Override 저장 오류", str(exc))
            return

        # 해당 group의 preview item에 override 즉시 반영
        preview_item = self._preview_items.get(group_id)
        if preview_item is not None:
            cfg = self._build_config_override()
            updated = apply_override_to_preview_item(
                conn, preview_item, override, config=cfg
            )
            # 메모리 내 preview item 갱신 — UI 표시 source.
            self._preview_items[group_id] = updated
            # 동일 group_id를 가진 모든 table row 갱신.
            self._refresh_preview_rows_for_group(group_id, updated)
            # Step 8 execute 가 사용하는 self._batch_preview["previews"] 리스트의
            # 같은 group entry 도 in-place 교체. apply_override_to_preview_item
            # 이 deepcopy 를 반환하므로 _preview_items 와 batch_preview 의 ref 가
            # 끊긴 상태 — 두 곳 모두 갱신해야 UI 표시와 실제 copy destination 이
            # 일치한다 (preview/execute consistency).
            self._replace_batch_preview_item(group_id, updated)

        conn.close()
        self.log_msg.emit(
            f"[INFO] 수동 override 적용: {filename} → "
            f"{override.get('series_canonical') or ''}/"
            f"{override.get('character_canonical') or ''}"
        )

    def _refresh_preview_rows_for_group(self, group_id: str, updated_item: dict) -> None:
        """
        _preview_rows 중 group_id가 일치하는 row의 테이블 셀을 갱신한다.

        하나의 group은 여러 destination을 가질 수 있으므로
        destinations 리스트와 순서를 맞춰 row별로 덮어쓴다.
        """
        dests = updated_item.get("destinations", [])
        total_dests = len(dests)
        dest_idx = 0
        source_path = updated_item.get("source_path", "")
        filename    = Path(source_path).name
        title       = updated_item.get("artwork_title", "")
        item_status, item_status_tip = self._compute_item_status(updated_item)
        inference_reasons = updated_item.get("inference_reasons") or []

        for row in range(len(self._preview_rows)):
            if self._preview_rows[row].get("group_id") != group_id:
                continue
            if dest_idx >= len(dests):
                break
            dest = dests[dest_idx]
            dest_idx += 1
            dest_pos = dest_idx  # 1-based

            dest_path = dest.get("dest_path", "")
            rule_type = dest.get("rule_type", "")
            will_copy = dest.get("will_copy", False)

            warn_parts: list[str] = []
            if dest.get("used_fallback"):
                warn_parts.append("fallback")
            if dest.get("conflict") not in (None, "", "none"):
                warn_parts.append(str(dest.get("conflict")))
            if dest.get("override_note"):
                warn_parts.append(dest["override_note"])
            # 추론 reason 은 raw_tags 에서 도출되므로 override 후에도 변하지 않는다.
            warn_parts.extend(inference_reasons)
            warn_str = ", ".join(warn_parts)

            rule_display = _format_preview_rule(rule_type)
            filename_cell = _format_multi_destination_filename(
                filename, dest_pos, total_dests
            )
            multi_lines = _multi_destination_tooltip_lines(
                dest_pos, total_dests, dests
            )
            base_tooltip = (
                f"파일: {filename}\n제목: {title}\n"
                f"규칙: {rule_display} ({rule_type})\n"
                f"분류사유·비고: {warn_str}\n"
                f"분류 경로: {dest_path}"
            ) + ("\n" + "\n".join(multi_lines) if multi_lines else "")
            status_tooltip = item_status_tip + (
                "\n" + "\n".join(multi_lines) if multi_lines else ""
            )
            col_values = [
                filename_cell, title,
                "분류됨" if will_copy else "제외",
                rule_display, warn_str, dest_path,
                item_status,
            ]
            for col, val in enumerate(col_values):
                existing = self._preview_table.item(row, col)
                if existing:
                    existing.setText(val)
                    existing.setToolTip(status_tooltip if col == 6 else base_tooltip)
                else:
                    it = QTableWidgetItem(val)
                    it.setToolTip(status_tooltip if col == 6 else base_tooltip)
                    self._preview_table.setItem(row, col, it)

        # 필터 재적용 (override 이후 상태 변경 반영)
        self._apply_filter(self._filter_mode)

    def _replace_batch_preview_item(self, group_id: str, updated: dict) -> bool:
        """``self._batch_preview["previews"]`` 의 group_id 일치 entry 를 in-place 교체.

        Step 7 UI 표시 source (``self._preview_items``) 와 Step 8 execute source
        (``self._batch_preview["previews"]``) 가 동일한 destinations 를 갖도록
        한다. ``_open_manual_override_dialog`` 에서 ``apply_override_to_preview_item``
        이 deepcopy 를 반환하기 때문에 두 자료구조의 dict reference 가 끊긴다 —
        본 helper 가 그 끊김을 복구한다.

        Step 8 의 ``_batch_preview`` 는 같은 dict object 를 reference 로 보유하고,
        ``previews`` 리스트도 공유하므로 list element 만 교체하면 두 단계 모두
        새 destinations 를 본다. 별도의 ``preview_ready`` 재emit 은 불필요.

        Returns
        -------
        bool
            교체에 성공했으면 True, batch_preview 가 없거나 매칭 entry 가 없어
            건너뛰면 False. 어느 경우에도 예외를 던지지 않는다 — manual override
            의 다른 경로 (DB 저장 / UI 갱신) 가 끊기지 않도록 한다.
        """
        if not isinstance(self._batch_preview, dict):
            return False
        previews = self._batch_preview.get("previews")
        if not isinstance(previews, list):
            return False
        for idx, item in enumerate(previews):
            if not isinstance(item, dict):
                continue
            if item.get("group_id") == group_id:
                previews[idx] = updated
                return True
        # 매칭 entry 없음 — 일관성 깨질 위험은 없으나 향후 디버깅을 위해 로그.
        self.log_msg.emit(
            f"[DEBUG] manual override batch_preview 매칭 entry 없음: "
            f"group_id={group_id[:8]}…"
        )
        return False

    # ------------------------------------------------------------------
    # 필터 + 상태 컬럼 helper
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_item_status(item: dict) -> tuple[str, str]:
        """preview_item의 상태 텍스트와 tooltip을 반환한다.

        Returns:
            (status_text, tooltip)
        """
        if _is_preview_item_manual_override(item):
            return "수동 보정", "사용자 지정 분류가 적용됨"
        if _is_preview_item_needs_review(item):
            ci = item.get("classification_info") or {}
            reason = ci.get("classification_reason", "")
            tip_map = {
                "series_detected_but_character_missing": "시리즈 감지됨, 캐릭터 미분류",
                "series_and_character_missing": "시리즈/캐릭터 모두 미분류",
            }
            tip = tip_map.get(reason, "분류 정보 확인 필요")
            # destinations에 used_fallback이 있는 경우 추가 설명
            for dest in item.get("destinations", []):
                if dest.get("used_fallback"):
                    tip = tip + " (표시명 fallback 사용)" if reason else "표시명 fallback 사용"
                    break
            return "확인 필요", tip
        return "", ""

    def _on_filter_changed(self, _index: int) -> None:
        """필터 ComboBox 선택 변경 시 호출."""
        mode = self._filter_combo.currentData() or "all"
        self._filter_mode = mode
        self._apply_filter(mode)

    def _apply_filter(self, mode: str) -> None:
        """현재 mode에 맞는 row만 표시, 나머지는 숨긴다.

        setRowHidden 방식을 사용하므로 row index 와 _preview_rows / _preview_items
        의 mapping이 그대로 유지된다.
        """
        for row_idx in range(self._preview_table.rowCount()):
            if row_idx >= len(self._preview_rows):
                self._preview_table.setRowHidden(row_idx, True)
                continue
            group_id = self._preview_rows[row_idx].get("group_id", "")
            item = self._preview_items.get(group_id)
            if item is None:
                self._preview_table.setRowHidden(row_idx, mode != "all")
                continue

            if mode == "all":
                visible = True
            elif mode == "needs_review":
                visible = _is_preview_item_needs_review(item)
            elif mode == "manual_override":
                visible = _is_preview_item_manual_override(item)
            else:
                visible = True

            self._preview_table.setRowHidden(row_idx, not visible)


# ── Step 8: Execute Classification ──────────────────────────────────────────

class _Step8Execute(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        self._batch_preview: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(_label("분류 실행", bold=True))
        layout.addWidget(_h_sep())

        layout.addWidget(QLabel(
            "ℹ 이 작업은 원본 파일을 이동/삭제하지 않습니다.\n"
            "  Classified 폴더에 복사본을 생성합니다.\n"
            "  copy_records와 undo_entries가 기록됩니다.\n"
            "  WorkLog에서 Undo할 수 있습니다."
        ))

        self._tbl = _kv_table([])
        layout.addWidget(self._tbl)

        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        layout.addWidget(self._result_lbl)

        self._progress_lbl = QLabel("대기 중")
        layout.addWidget(self._progress_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.hide()
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._btn_execute = QPushButton("▶ 분류 실행")
        self._btn_execute.setEnabled(False)
        self._btn_execute.setToolTip(
            "먼저 미리보기를 생성하고 결과를 확인해야 분류를 실행할 수 있습니다."
        )
        self._btn_execute.clicked.connect(self._on_execute)
        btn_row.addWidget(self._btn_execute)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        self._execute_thread: Optional[_ExecuteThread] = None

    def set_preview(self, batch_preview: dict) -> None:
        self._batch_preview = batch_preview
        self._btn_execute.setEnabled(bool(batch_preview))
        total_groups = len(batch_preview.get("previews", []))
        rows = [
            ("대상 그룹",    str(total_groups)),
            ("예상 복사본",  str(batch_preview.get("estimated_copies", 0))),
            ("예상 용량",    _fmt_size(batch_preview.get("estimated_bytes", 0))),
        ]
        self._tbl.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self._tbl.setItem(r, 0, QTableWidgetItem(k))
            self._tbl.setItem(r, 1, QTableWidgetItem(v))

    def refresh(self) -> None:
        pass

    def _on_execute(self) -> None:
        if not self._batch_preview:
            QMessageBox.warning(self._wizard, "미리보기 필요", "먼저 7단계에서 미리보기를 생성하세요.")
            return
        if self._execute_thread and self._execute_thread.isRunning():
            return

        # Stale preview gate — Step 7 가 dirty 상태이면 사용자에게 확인 후 진행.
        # 분류 기준이 바뀐 뒤 preview 를 다시 생성하지 않고 execute 했을 때 옛
        # destination 으로 파일이 복사되는 사고를 방지한다. classification /
        # destination / file copy 로직 자체는 변경하지 않는다 — 사용자 의사
        # 확인만 추가.
        if not self._confirm_proceed_with_dirty_preview():
            return

        if QMessageBox.question(
            self._wizard, "분류 실행 확인",
            f"복사본 {self._batch_preview.get('estimated_copies',0)}개를 생성합니다.\n계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        self._btn_execute.setEnabled(False)
        self._btn_execute.setText("실행 중…")
        total_groups = len(self._batch_preview.get("previews", []))
        self._progress.setRange(0, max(total_groups, 1))
        self._progress.setValue(0)
        self._progress.show()
        self._progress_lbl.setText(f"실행 준비 중 — 대상 {total_groups}개 그룹")
        self._show_loading(
            "Step 8: 분류 실행",
            "분류 작업을 실행하는 중입니다…",
            detail=f"대상 그룹 {total_groups}개를 순서대로 처리합니다.",
            total=max(total_groups, 1),
            current=0,
        )
        self._execute_thread = _ExecuteThread(
            self._conn_factory, self._batch_preview, self._config(), self
        )
        self._execute_thread.log_msg.connect(self.log_msg)
        self._execute_thread.log_msg.connect(self._mirror_loading_log)
        self._execute_thread.progress.connect(self._on_execute_progress)
        self._execute_thread.done.connect(self._on_execute_done)
        self._execute_thread.start()

    def _find_step7_preview(self) -> Optional["_Step7Preview"]:
        """wizard._panels 에서 _Step7Preview 인스턴스를 찾아 반환.

        Step 7 가 없거나 wizard reference 가 끊긴 경우 None — 호출자는 fail-safe
        로 기존 동작을 유지해야 한다.
        """
        wizard = getattr(self, "_wizard", None)
        panels = getattr(wizard, "_panels", None) if wizard is not None else None
        if not panels:
            return None
        for panel in panels:
            if isinstance(panel, _Step7Preview):
                return panel
        return None

    def _confirm_proceed_with_dirty_preview(self) -> bool:
        """Step 7 preview 가 stale 상태이면 사용자에게 확인 dialog 를 띄운다.

        Returns
        -------
        bool
            True  — 진행해도 됨 (clean 이거나 사용자가 "그래도 실행" 선택).
            False — 사용자가 취소 — execute 중단.

        - Step 7 가 없거나 dirty API 가 없으면 fail-safe 로 True 반환 (기존 동작
          유지).
        - dirty 상태에서 사용자가 "그래도 실행" 을 선택해도 dirty flag 는 유지
          한다 — preview 자체가 최신이 된 것은 아니므로.
        """
        step7 = self._find_step7_preview()
        if step7 is None:
            return True
        is_dirty_fn = getattr(step7, "is_preview_dirty", None)
        if not callable(is_dirty_fn):
            return True
        try:
            if not is_dirty_fn():
                return True
        except Exception:
            # is_preview_dirty 가 예외 던지면 안전하게 진행 허용.
            return True

        box = QMessageBox(self._wizard)
        box.setWindowTitle("미리보기가 최신 상태가 아닙니다")
        box.setText(
            "분류 기준이 변경되어 현재 미리보기 결과가 이전 설정 기준일 수 있습니다.\n"
            "정확한 결과를 위해 분류 미리보기를 다시 생성하는 것이 좋습니다."
        )
        box.setIcon(QMessageBox.Icon.Warning)
        cancel_btn = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        proceed_btn = box.addButton("그래도 실행", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        return box.clickedButton() is proceed_btn

    def _on_execute_progress(self, done: int, total: int, message: str) -> None:
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(done)
        self._progress_lbl.setText(f"{done}/{total} — {message}")

    def _on_execute_done(self, result: dict) -> None:
        self._btn_execute.setEnabled(True)
        self._btn_execute.setText("▶ 분류 실행")
        self._progress.hide()
        if result.get("success", False):
            base_msg = (
                f"✅ 완료 — 복사: {result.get('copied',0)}, "
                f"스킵: {result.get('skipped',0)}, "
                f"entry_id: {result.get('entry_id','')[:8]}…"
            )
            json_only_count = self._query_json_only_count()
            if json_only_count > 0:
                base_msg += (
                    f"\n⚠ 메타데이터 JSON-only 저장: {json_only_count}건"
                    " — ExifTool 설정을 확인하세요."
                    " Windows Explorer 세부 정보에는 태그/제목이 표시되지 않을 수 있습니다."
                )
            self._result_lbl.setText(base_msg)
        else:
            self._result_lbl.setText(
                f"❌ 실패: {result.get('error', '알 수 없는 오류')}"
            )
        self._progress_lbl.setText("완료")
        self.refresh_main.emit()

    def _on_execute_progress(self, done: int, total: int, message: str) -> None:
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(done)
        self._progress_lbl.setText(f"{done}/{total} — {message}")
        self._update_loading(
            message="분류 작업을 실행하는 중입니다…",
            detail=message,
            current=done,
            total=total,
        )

    def _on_execute_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="wizard.execute")
        self._hide_loading()
        self._btn_execute.setEnabled(True)
        self._btn_execute.setText("▶ 분류 실행")
        self._progress.hide()
        if result.get("success", False):
            base_msg = (
                f"✅ 완료 — 복사: {result.get('copied',0)}, "
                f"스킵: {result.get('skipped',0)}, "
                f"entry_id: {result.get('entry_id','')[:8]}…"
            )
            json_only_count = self._query_json_only_count()
            if json_only_count > 0:
                base_msg += (
                    f"\n⚠ 메타데이터 JSON-only 저장: {json_only_count}건"
                    " — ExifTool 설정을 확인하세요."
                    " Windows Explorer 세부 정보에는 태그/제목이 표시되지 않을 수 있습니다."
                )
            self._result_lbl.setText(base_msg)
        else:
            self._result_lbl.setText(
                f"❌ 실패: {result.get('error', '알 수 없는 오류')}"
            )
        self._progress_lbl.setText("완료")
        _log_phase("postprocess.start", 0.0, op="wizard.execute")
        _t_emit = time.perf_counter()
        self.refresh_main.emit()
        _log_phase("refresh_main.emit", (time.perf_counter() - _t_emit) * 1000, op="wizard.execute")
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="wizard.execute")

    def _query_json_only_count(self) -> int:
        """DB에서 metadata_sync_status='json_only' 그룹 수를 반환한다."""
        try:
            conn = self._conn_factory()
            row = conn.execute(
                "SELECT COUNT(*) FROM artwork_groups"
                " WHERE metadata_sync_status = 'json_only'"
            ).fetchone()
            conn.close()
            return int(row[0]) if row else 0
        except Exception:
            return 0


# ── Step 9: Result / Undo ───────────────────────────────────────────────────

class _Step9Result(_StepPanel):
    def __init__(self, wizard, parent=None):
        super().__init__(wizard, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_label("결과 / Undo", bold=True))
        layout.addWidget(_h_sep())

        self._tbl = QTableWidget(0, 5)
        self._tbl.setHorizontalHeaderLabels(["작업 시각", "유형", "상태", "복사본 수", "만료일"])
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._tbl)

        btn_row = QHBoxLayout()
        _btn_worklog = QPushButton("🕘 작업 로그 열기")
        _btn_worklog.setToolTip(
            "분류 실행 이력과 Undo 가능 여부를 확인합니다."
        )
        _btn_worklog.clicked.connect(self._open_work_log)
        btn_row.addWidget(_btn_worklog)

        _btn_classified = QPushButton("📂 Classified 폴더 열기")
        _btn_classified.setToolTip(
            "분류 결과가 저장된 Classified 폴더를 탐색기로 엽니다."
        )
        _btn_classified.clicked.connect(self._open_classified)
        btn_row.addWidget(_btn_classified)

        _btn_restart = QPushButton("처음으로")
        _btn_restart.setToolTip("Step 1로 돌아가 새 작업을 시작합니다.")
        _btn_restart.clicked.connect(lambda: self._wizard._go_to_step(0))
        btn_row.addWidget(_btn_restart)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

    def refresh(self) -> None:
        try:
            conn = self._conn_factory()
            from core.undo_manager import list_undo_entries
            entries = list_undo_entries(conn)
            conn.close()
        except Exception:
            return

        self._tbl.setRowCount(len(entries))
        for r, e in enumerate(entries):
            from core.undo_manager import STATUS_LABEL
            from datetime import datetime
            try:
                dt_str = datetime.fromisoformat(e["performed_at"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt_str = e.get("performed_at", "")
            self._tbl.setItem(r, 0, QTableWidgetItem(dt_str))
            self._tbl.setItem(r, 1, QTableWidgetItem(e.get("operation_type", "")))
            self._tbl.setItem(r, 2, QTableWidgetItem(STATUS_LABEL.get(e.get("undo_status", ""), e.get("undo_status", ""))))
            self._tbl.setItem(r, 3, QTableWidgetItem(str(e.get("copy_count", ""))))
            self._tbl.setItem(r, 4, QTableWidgetItem((e.get("undo_expires_at") or "")[:10]))

    def _open_work_log(self) -> None:
        try:
            from app.views.work_log_view import WorkLogView
            conn = self._conn_factory()
            dlg  = WorkLogView(conn, parent=self._wizard)
            dlg.exec()
            conn.close()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self._wizard, "오류", str(exc))

    def _open_classified(self) -> None:
        cfg = self._config()
        classified = cfg.get("classified_dir", "")
        if not classified:
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", classified], **no_window_kwargs())
            elif sys.platform == "darwin":
                subprocess.Popen(["open", classified])
            else:
                subprocess.Popen(["xdg-open", classified])
        except Exception as exc:
            logger.warning("폴더 열기 실패: %s", exc)


# ---------------------------------------------------------------------------
# 메인 Wizard 다이얼로그
# ---------------------------------------------------------------------------

class WorkflowWizardView(QDialog):
    """
    Aru Archive 작업 마법사.

    사용법:
        wizard = WorkflowWizardView(conn_factory, config, config_path, parent=self)
        wizard.refresh_main.connect(self._refresh_gallery)
        wizard.exec()
    """

    refresh_main                    = Signal()   # MainWindow가 갤러리/카운트를 갱신해야 할 때
    exact_duplicate_scan_requested  = Signal()   # Step 3에서 완전 중복 검사를 MainWindow handler에 위임
    visual_duplicate_scan_requested = Signal()   # Step 3에서 시각 중복 검사를 MainWindow handler에 위임

    def __init__(
        self,
        conn_factory,
        config: dict,
        config_path: str,
        *,
        parent=None,
        current_filter_group_ids_provider=None,
        selected_group_ids_provider=None,
    ) -> None:
        super().__init__(parent)
        self._conn_factory = conn_factory
        self._config       = config
        self._config_path  = config_path
        self._loading_dialog: Optional[LoadingOverlayDialog] = None
        # Step 7 preview scope 가 'current_filter' / 'selected' 일 때 사용. 제공되지
        # 않으면 빈 list 가 전달되며, batch_classifier 가 빈 candidate 처리한다.
        # MainWindow 외에서 wizard 를 띄우거나 단위 테스트에서는 None 그대로 사용.
        self._current_filter_group_ids_provider = current_filter_group_ids_provider
        self._selected_group_ids_provider = selected_group_ids_provider

        self.setWindowTitle("🧭 Aru Archive 작업 마법사")
        self.setMinimumSize(800, 600)
        self.resize(920, 680)

        self._build_ui()
        self._go_to_step(0)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── 진행 표시 헤더 ──
        header = QWidget()
        header.setStyleSheet("background:#2B1720; padding:6px;")
        hbox = QHBoxLayout(header)
        hbox.setSpacing(4)
        hbox.setContentsMargins(8, 4, 8, 4)

        self._step_btns: list[QPushButton] = []
        for idx in range(len(_STEPS)):
            label = _visible_step_button_label(idx)
            # hidden step 의 버튼은 사용자에게 보이지 않으므로 텍스트 없어도 됨.
            btn = QPushButton(label or "")
            btn.setFlat(True)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, i=idx: self._go_to_step(i))
            btn.setStyleSheet(
                "QPushButton {color:#8F6874; background:transparent; border:none; font-size:11px;}"
                "QPushButton:hover {color:#D8AEBB;}"
            )
            # _HIDDEN_STEP_INDICES에 해당하는 단계 버튼은 숨긴다 (패널은 _stack에 유지)
            if idx in _HIDDEN_STEP_INDICES:
                btn.setVisible(False)
            self._step_btns.append(btn)
            hbox.addWidget(btn)
            # 화살표는 hidden step 직전/직후 모두 끄거나 표시 등 추가 정책이 필요하면 후속 PR.
            # 이번 PR 은 번호/라벨만 정리. 화살표 위치 유지.
            if idx < len(_STEPS) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet("color:#4A2030; font-size:10px;")
                # hidden step 양쪽 화살표는 함께 숨겨 사용자가 끊긴 chevron 을 보지 않도록 한다.
                if idx in _HIDDEN_STEP_INDICES or (idx + 1) in _HIDDEN_STEP_INDICES:
                    arrow.setVisible(False)
                hbox.addWidget(arrow)

        root.addWidget(header)

        # ── 단계 제목 ──
        self._step_title = QLabel("")
        self._step_title.setStyleSheet(
            "background:#1A0F14; color:#D8AEBB; font-size:14px; "
            "font-weight:bold; padding:8px 16px;"
        )
        root.addWidget(self._step_title)

        # ── 스텝 스택 ──
        self._stack = QStackedWidget()
        self._panels: list[_StepPanel] = []

        for PanelClass in [
            _Step1Root, _Step2Scan, _Step3Meta, _Step4EnrichModern,
            _Step5ClassifyLevel, _Step6Retag, _Step7Preview, _Step8Execute,
            _Step9Result,
        ]:
            panel = PanelClass(self)
            panel.setContentsMargins(16, 12, 16, 8)
            panel.log_msg    .connect(self._on_log)
            panel.refresh_main.connect(self.refresh_main)
            # Step 7 → Step 8 연결
            if isinstance(panel, _Step7Preview):
                panel.preview_ready.connect(self._on_preview_ready)
            scroll = QScrollArea()
            scroll.setWidget(panel)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            self._stack.addWidget(scroll)
            self._panels.append(panel)

        root.addWidget(self._stack, 1)

        # ── 로그 패널 ──
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFixedHeight(70)
        self._log_area.setStyleSheet(
            "QTextEdit {background:#110A0D; color:#8F8890; font-size:11px; border:none;}"
        )
        root.addWidget(self._log_area)

        # ── 네비게이션 ──
        nav = QWidget()
        nav.setStyleSheet("background:#1A0F14; padding:4px;")
        nav_box = QHBoxLayout(nav)
        nav_box.setContentsMargins(12, 6, 12, 6)

        self._btn_prev    = QPushButton("◀ 이전")
        self._btn_next    = QPushButton("다음 ▶")
        self._btn_refresh = QPushButton("🔄 새로고침")
        self._btn_close   = QPushButton("닫기")

        self._btn_prev   .clicked.connect(self._on_prev)
        self._btn_next   .clicked.connect(self._on_next)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_close  .clicked.connect(self.accept)

        for btn in (self._btn_prev, self._btn_next, self._btn_refresh):
            nav_box.addWidget(btn)
        nav_box.addStretch()
        nav_box.addWidget(self._btn_close)

        root.addWidget(nav)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _db_path(self) -> str:
        cfg = self._config
        raw = cfg.get("db", {}).get("path", "")
        if raw:
            return raw
        dd = cfg.get("data_dir", "")
        return f"{dd}/.runtime/aru_archive.db" if dd else "aru_archive.db"

    def _ensure_loading_dialog(self) -> LoadingOverlayDialog:
        if self._loading_dialog is None:
            self._loading_dialog = LoadingOverlayDialog(self)
        return self._loading_dialog

    def _show_loading(
        self,
        title: str,
        message: str,
        *,
        detail: str = "",
        total: Optional[int] = None,
        current: int = 0,
    ) -> None:
        _t0 = time.perf_counter()
        dialog = self._ensure_loading_dialog()
        dialog.set_title_text(title)
        dialog.set_message_text(message)
        dialog.set_detail_text(detail)
        if total is None:
            dialog.set_indeterminate("작업 중…")
        else:
            dialog.set_progress(current, total, f"{current}/{max(total, 1)}")
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        QApplication.processEvents()
        _log_phase("loading.show", (time.perf_counter() - _t0) * 1000, title=title)

    def _update_loading(
        self,
        *,
        message: Optional[str] = None,
        detail: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        dialog = self._loading_dialog
        if dialog is None:
            return
        if message is not None:
            dialog.set_message_text(message)
        if detail is not None:
            dialog.set_detail_text(detail)
        if current is not None and total is not None:
            dialog.set_progress(current, total, f"{current}/{max(total, 1)}")

    def _hide_loading(self) -> None:
        if self._loading_dialog is None:
            return
        _t0 = time.perf_counter()
        self._loading_dialog.hide()
        _log_phase("loading.hide", (time.perf_counter() - _t0) * 1000)

    # Loading dialog detail label 표시용 max characters. 원문은 wizard 의
    # _log_area (QTextEdit) 와 호출자 logger 에 보존되므로 detail 한 줄을 짧게
    # 잘라도 정보 손실 없음. dialog 측 set_detail_text 도 자체 truncate 하지만
    # caller 단에서 짧게 보내는 게 중복 호출 비용 / Qt resize 비용을 더 줄인다.
    _DETAIL_MIRROR_MAX_CHARS = 140

    def _mirror_loading_log(self, message: str) -> None:
        dialog = self._loading_dialog
        if dialog is None:
            return
        clean = message.strip()
        for prefix in ("[INFO] ", "[WARN] ", "[ERROR] "):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break
        if not clean:
            return
        # Layout 안정화 — 긴 한 줄을 detail 로 그대로 넘기면 wrap 으로 dialog
        # height 가 흔들린다. 원문은 _log_area 에 이미 추가됨.
        if len(clean) > self._DETAIL_MIRROR_MAX_CHARS:
            clean = clean[: self._DETAIL_MIRROR_MAX_CHARS - 1].rstrip() + "…"
        dialog.set_detail_text(clean)

    def _go_to_step(self, idx: int) -> None:
        idx = max(0, min(idx, len(_STEPS) - 1))
        # _HIDDEN_STEP_INDICES에 해당하는 단계는 자동으로 건너뛴다.
        # 방향은 _current 기준으로 판단 (없으면 forward).
        if idx in _HIDDEN_STEP_INDICES:
            direction = 1 if idx >= getattr(self, "_current", 0) else -1
            idx = max(0, min(idx + direction, len(_STEPS) - 1))
        self._current = idx
        self._stack.setCurrentIndex(idx)

        # 헤더 강조
        for i, btn in enumerate(self._step_btns):
            if i == idx:
                btn.setStyleSheet(
                    "QPushButton {color:#FF9EBB; background:transparent; "
                    "border:none; font-size:11px; font-weight:bold;}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {color:#8F6874; background:transparent; "
                    "border:none; font-size:11px;}"
                    "QPushButton:hover {color:#D8AEBB;}"
                )

        # 사용자에게 보이는 번호 (hidden step 제외) + 한국어 제목.
        # hidden step 진입 시에는 "자동 진행 단계: ..." 형식 (호출 흐름이 hidden 으로
        # 강제 진입할 일은 거의 없지만 방어적으로 처리).
        self._step_title.setText(_visible_step_title_text(idx))
        self._btn_prev.setEnabled(idx > 0)
        self._btn_next.setEnabled(idx < len(_STEPS) - 1)

        # 단계 진입 시 자동 새로고침
        self._panels[idx].refresh()

    def _on_prev(self) -> None:
        self._go_to_step(self._current - 1)

    def _on_next(self) -> None:
        self._go_to_step(self._current + 1)

    def _on_refresh(self) -> None:
        self._panels[self._current].refresh()

    def _on_log(self, msg: str) -> None:
        self._log_area.append(msg)
        self._mirror_loading_log(msg)

    def _on_preview_ready(self, batch_preview: dict) -> None:
        # Step 8에 preview 전달
        step8 = self._panels[7]
        if isinstance(step8, _Step8Execute):
            step8.set_preview(batch_preview)

    # ------------------------------------------------------------------
    # 외부 신호 처리 — Local Dictionary 변경 알림
    # ------------------------------------------------------------------

    def handle_local_dictionary_changed(self) -> None:
        """MainWindow 의 ``local_dictionary_changed`` signal slot.

        사용자 사전 (tag_aliases / tag_localizations) 이 변경되었을 때
        MainWindow 가 emit 한다. wizard 가 살아 있다면 Step 7 preview 의
        dirty 상태를 표시해 사용자에게 미리보기 재생성을 유도한다.

        주의: wizard 는 현재 ``dlg.exec()`` 로 ApplicationModal 이라 MainWindow
        Top Menu 의 dict 변경 dialog 가 열리는 동안 wizard 와 동시에 살아 있을
        일이 거의 없다. 본 slot 은 향후 wizard non-modal 화 또는 in-wizard
        dict 편집 도입을 대비한 defense-in-depth.

        Step 7 패널이 없거나 ``mark_preview_dirty`` 가 부재하면 silently
        no-op — 다른 dict 변경 / UI 갱신 흐름을 끊지 않는다.
        """
        for panel in self._panels:
            if isinstance(panel, _Step7Preview):
                marker = getattr(panel, "mark_preview_dirty", None)
                if callable(marker):
                    try:
                        marker("사용자 사전이 변경되었습니다.")
                    except Exception:
                        pass
                return
