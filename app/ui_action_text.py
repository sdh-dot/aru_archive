from __future__ import annotations

SCAN_MENU_LABEL = "🔍 이미지 스캔"
SCAN_BUTTON_LABEL = "🔍 이미지 스캔 실행"
SCAN_TOOLTIP = "Inbox 폴더를 스캔해 파일을 등록하고 DB를 갱신합니다."

PIXIV_META_LABEL = "🖼 Pixiv 메타데이터 가져오기"
PIXIV_META_TOOLTIP = (
    "파일명에서 Pixiv artwork_id를 추출하고 "
    "Pixiv 메타데이터를 조회해 파일과 DB에 기록합니다."
)
PIXIV_META_TOOLTIP_MISSING = (
    "파일명에서 Pixiv artwork_id를 추출할 수 없습니다.\n"
    "형식: {artwork_id}_p{n}.ext (예: 141100516_p0.jpg)"
)

XMP_RETRY_LABEL = "🔄 XMP 재처리"
XMP_RETRY_SELECTED_LABEL = "🔄 선택 XMP 재처리"
XMP_RETRY_ALL_LABEL = "🔄 전체 XMP 재처리"
XMP_RETRY_TOOLTIP = (
    "ExifTool로 XMP 표준 필드를 다시 기록합니다.\n"
    "json_only / xmp_write_failed 상태에서 사용합니다."
)

EXPLORER_META_REPAIR_LABEL = "🛠 Explorer 메타 복구"
EXPLORER_META_REPAIR_SELECTED_LABEL = "🛠 선택 Explorer 메타 복구"
EXPLORER_META_REPAIR_TOOLTIP = (
    "Windows 탐색기용 제목, 태그, 만든 이를 다시 기록합니다."
)

REINDEX_LABEL = "DB 재색인"
REINDEX_TOOLTIP = "선택한 작품의 파일 상태와 메타데이터를 다시 읽어 DB를 갱신합니다."

READ_EMBEDDED_META_LABEL = "파일 내 메타데이터 읽기"
READ_EMBEDDED_META_TOOLTIP = "선택 파일의 AruArchive JSON / XMP를 읽습니다."
