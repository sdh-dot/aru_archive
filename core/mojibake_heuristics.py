"""core/mojibake_heuristics.py — Shared mojibake detection heuristics.

Centralized heuristic logic used by:
  - tools/diagnose_mojibake.py  (PR-4: read-only DB diagnosis)
  - tools/repair_mojibake_db.py (PR-5: safe DB repair)
  - core/tag_pack_loader.py     (PR-6: import-time lint / block)

Signal taxonomy
---------------
Strong signals — import is blocked when any strong signal fires:
  replacement-char        U+FFFD or U+25A1 found in text.
  ?-runs                  Three or more consecutive '?' characters.
  underscore-placeholder  Three or more consecutive '_' with < 30 % alphanumeric.
  punctuation-heavy       ASCII punctuation > 50 % of all characters.

Weak signals — import is warned but allowed; the row may be skipped:
  latin1-mojibake         Latin-1 / CP932 indicator characters (Ã/Â/ã …).
  locale-mismatch         Expected locale script (ko/ja) is under-represented.
"""
from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Signal sets
# ---------------------------------------------------------------------------

STRONG_SIGNALS: frozenset[str] = frozenset({
    "replacement-char",
    "?-runs",
    "underscore-placeholder",
    "punctuation-heavy",
})

WEAK_SIGNALS: frozenset[str] = frozenset({
    "latin1-mojibake",
    "locale-mismatch",
})

# ---------------------------------------------------------------------------
# Latin-1 / CP932 mojibake indicator characters
# ---------------------------------------------------------------------------

# Characters that commonly appear when UTF-8 multi-byte sequences are
# misread as ISO-8859-1 or CP1252.
_LATIN1_MOJIBAKE_CHARS: frozenset[str] = frozenset(
    "ÃÂãâ¢¥ÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáäåæçèéêëìíîïðñòóôõöøùúûüýþÿ"
)

# U+FFFD REPLACEMENT CHARACTER
_REPLACEMENT_CHAR = "�"  # noqa: RUF001  (U+FFFD, not a typo)

# U+25A1 WHITE SQUARE (also used in some mojibake contexts)
_WHITE_SQUARE = "□"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_suspected_mojibake(
    text: Optional[str],
    locale: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Return (suspected, reasons) for *text*.

    This is the canonical implementation.  ``tools/diagnose_mojibake.py``
    and ``tools/repair_mojibake_db.py`` both import this function.

    Parameters
    ----------
    text:
        The string to check.  Non-string or empty → ``(False, [])``.
    locale:
        Optional locale hint (``"ko"``, ``"ja"``, ``"en"``, …).
        Used only for the locale-mismatch heuristic.

    Returns
    -------
    (suspected, reasons)
        *suspected* is ``True`` when at least one heuristic fired.
        *reasons* is a list of short reason keys (see module docstring).
    """
    if not isinstance(text, str) or not text:
        return False, []

    reasons: list[str] = []

    # 1. Replacement character (U+FFFD / U+25A1)
    if _REPLACEMENT_CHAR in text or _WHITE_SQUARE in text:
        reasons.append("replacement-char")

    # 2. Latin-1 / CP932 mojibake characters (>= 2 occurrences)
    latin1_count = sum(1 for ch in text if ch in _LATIN1_MOJIBAKE_CHARS)
    if latin1_count >= 2:
        reasons.append("latin1-mojibake")

    # 3. Three or more consecutive '?'
    if "???" in text:
        reasons.append("?-runs")

    # 4. Underscore placeholder: 3+ consecutive '_' AND < 30 % alphanumeric
    if "___" in text:
        alnum_ratio = sum(1 for ch in text if ch.isalnum()) / max(len(text), 1)
        if alnum_ratio < 0.30:
            reasons.append("underscore-placeholder")

    # 5. Locale mismatch — expected script under-represented
    if locale in ("ko", "ja"):
        total = max(len(text), 1)
        if locale == "ko":
            ko_count = sum(1 for ch in text if "가" <= ch <= "힣")
            if (ko_count / total) < 0.30:
                reasons.append("locale-mismatch")
        else:  # locale == "ja"
            ja_count = sum(
                1 for ch in text
                if ("぀" <= ch <= "ゟ")   # hiragana
                or ("゠" <= ch <= "ヿ")   # katakana
                or ("一" <= ch <= "鿿")   # CJK unified (kanji)
            )
            if (ja_count / total) < 0.30:
                reasons.append("locale-mismatch")

    # 6. Punctuation-heavy: ASCII punctuation > 50 %
    ascii_punct_count = sum(
        1 for ch in text
        if 0x21 <= ord(ch) <= 0x7E and not ch.isalnum()
    )
    if (ascii_punct_count / max(len(text), 1)) > 0.50:
        reasons.append("punctuation-heavy")

    return bool(reasons), reasons


def classify_mojibake_severity(reasons: list[str]) -> str:
    """Classify detected reasons into a severity tier.

    Returns
    -------
    ``"strong"``
        At least one reason is in :data:`STRONG_SIGNALS`.
        Import should be **blocked**.
    ``"weak"``
        At least one reason is in :data:`WEAK_SIGNALS` (but no strong).
        Import should be **warned** (row may be skipped).
    ``"clean"``
        No reasons.  Normal import proceeds.
    """
    if any(r in STRONG_SIGNALS for r in reasons):
        return "strong"
    if any(r in WEAK_SIGNALS for r in reasons):
        return "weak"
    return "clean"
