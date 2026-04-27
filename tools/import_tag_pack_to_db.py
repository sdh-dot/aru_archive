#!/usr/bin/env python3
"""
Tag Pack → Runtime DB Importer.

사용법:
  python tools/import_tag_pack_to_db.py \\
      --db C:/Users/seodh/AruArchive/.runtime/aru.db \\
      --pack docs/tag_pack_export_localized_ko_ja_failure_patch_v2.json

정책:
  - INSERT OR IGNORE (기존 데이터 덮어쓰지 않음)
  - _review 필드 무시
  - 결과 요약 출력
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Tag Pack → DB Importer")
    parser.add_argument("--db",   "-d", required=True, help="SQLite DB 경로")
    parser.add_argument("--pack", "-p", required=True, help="Tag pack JSON 경로")
    parser.add_argument("--verify", action="store_true",
                        help="import 후 주요 alias 확인 출력")
    args = parser.parse_args()

    db_path   = Path(args.db)
    pack_path = Path(args.pack)

    if not db_path.exists():
        print(f"[ERROR] DB 파일 없음: {db_path}", file=sys.stderr)
        return 1
    if not pack_path.exists():
        print(f"[ERROR] pack 파일 없음: {pack_path}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from db.database import initialize_database
    from core.tag_pack_loader import import_localized_tag_pack

    print(f"[INFO] DB:   {db_path}")
    print(f"[INFO] Pack: {pack_path}")

    conn = initialize_database(str(db_path))

    before_char = conn.execute(
        "SELECT COUNT(*) FROM tag_aliases WHERE tag_type='character'"
    ).fetchone()[0]
    before_ser = conn.execute(
        "SELECT COUNT(*) FROM tag_aliases WHERE tag_type='series'"
    ).fetchone()[0]
    print(f"[INFO] Before import — character aliases: {before_char}, series aliases: {before_ser}")

    result = import_localized_tag_pack(conn, pack_path)

    after_char = conn.execute(
        "SELECT COUNT(*) FROM tag_aliases WHERE tag_type='character'"
    ).fetchone()[0]
    after_ser = conn.execute(
        "SELECT COUNT(*) FROM tag_aliases WHERE tag_type='series'"
    ).fetchone()[0]

    print(f"\n[INFO] Import result:")
    print(f"  series_aliases:    {result.get('series_aliases', 0)}")
    print(f"  character_aliases: {result.get('character_aliases', 0)}")
    print(f"  localizations:     {result.get('localizations', 0)}")
    print(f"  review_items:      {result.get('review_items', 0)}")
    print(f"  conflicts:         {len(result.get('conflicts', []))}")
    if result.get("conflicts"):
        for c in result["conflicts"][:5]:
            print(f"    conflict: {c['alias']!r} existing={c['existing_canonical']!r} pack={c['pack_canonical']!r}")

    print(f"\n[INFO] After import  — character aliases: {after_char} (+{after_char-before_char}), "
          f"series aliases: {after_ser} (+{after_ser-before_ser})")

    if args.verify:
        print("\n[VERIFY] Key aliases:")
        targets = [
            "十六夜ノノミ", "ノノミ", "合歓垣フブキ", "フブキ", "後部木",
            "羽川ハスミ", "ハスミ", "黒崎コユキ", "コユキ",
            "七神リン", "リン", "桐藤ナギサ", "ナギサ",
            "猫塚ヒビキ", "京極サツキ", "サツキ", "鷲見セリナ", "セリナ",
            "春原シュン", "仲正イチカ", "浦和ハナコ", "伊落マリー", "マリー",
        ]
        for t in targets:
            rows = conn.execute(
                "SELECT alias, canonical, tag_type, parent_series, enabled "
                "FROM tag_aliases WHERE alias=?", (t,)
            ).fetchall()
            if rows:
                for r in rows:
                    status = "OK" if r[4] else "DISABLED"
                    print(f"  [{status}] {r[0]} -> {r[1]} ({r[2]}, series={r[3]!r})")
            else:
                print(f"  [MISSING] {t}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
