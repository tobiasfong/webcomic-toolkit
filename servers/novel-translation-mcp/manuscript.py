"""
manuscript.py — parses a novel manuscript (.docx) into chapters, on demand.

No caching: every call re-opens the file and re-parses it. python-docx parsing a
50k-word manuscript takes well under a second, and staleness bugs are worse than
that cost (a stale in-memory copy of the manuscript is exactly the kind of thing
that wastes a human's review time chasing a "bug" that was fixed on disk an hour
ago). Re-parsing per call means get_chapter/search_manuscript always reflect
what's actually on disk right now.

Two heading conventions are recognised:
  EN: "Chapter 19: Actually, I'm not the Saintess"
  JA: "第十九話　実は聖女ではありません" (kanji numerals, 話 for web serialization
      or 章 for a bound-volume convention — see TRANSLATION-LESSONS.md §3.1.8)

Italic runs are marked with *asterisks* in extracted text (EN italics mark internal
thought in this manuscript — see TRANSLATION-LESSONS.md §1.5, §3.1.5 — so this needs
to survive extraction even though plain-text tools like pandoc drop it silently).
"""

import re
import docx

_EN_HEADING_RE = re.compile(r"^\s*chapter\s+(\d+)\s*:?\s*(.*)$", re.IGNORECASE)
_JA_HEADING_RE = re.compile(r"^\s*第([0-9〇一二三四五六七八九十百千]+)[話章]\s*(.*)$")

_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_to_int(s: str) -> int:
    """Convert a kanji numeral (e.g. '十九', '二十一', '百三') to an int.

    Handles the range actually needed for chapter numbers (1-999). Falls back to
    parsing bare Arabic digits if the string is already numeric.
    """
    if s.isdigit():
        return int(s)

    total = 0
    section = 0  # accumulates within a "千" group; not needed past hundreds in practice
    num = 0
    for ch in s:
        if ch in _KANJI_DIGITS:
            num = _KANJI_DIGITS[ch]
        elif ch == "十":
            section += (num or 1) * 10
            num = 0
        elif ch == "百":
            section += (num or 1) * 100
            num = 0
        elif ch == "千":
            total += (num or 1) * 1000
            section = 0
            num = 0
        else:
            continue
    return total + section + num


def _paragraph_text(paragraph) -> str:
    """Paragraph text with italic runs wrapped in *asterisks*, matching adjacent
    italic runs into one span so 'the *whole thought*' doesn't fragment into
    '*the* *whole* *thought*'."""
    parts = []
    buf = []
    buf_italic = None
    for run in paragraph.runs:
        text = run.text
        if not text:
            continue
        is_italic = bool(run.italic)
        if buf_italic is None or is_italic == buf_italic:
            buf.append(text)
            buf_italic = is_italic
        else:
            parts.append(f"*{''.join(buf)}*" if buf_italic else "".join(buf))
            buf = [text]
            buf_italic = is_italic
    if buf:
        parts.append(f"*{''.join(buf)}*" if buf_italic else "".join(buf))
    return "".join(parts)


class ManuscriptError(RuntimeError):
    pass


def parse_chapters(docx_path: str, lang: str) -> dict[int, dict]:
    """Parse a .docx into {chapter_number: {"title": str, "paragraphs": [str]}}.

    `lang` picks the heading convention: "en" for "Chapter N: Title", "ja" for
    "第N話/章　Title" (kanji numerals).
    """
    try:
        document = docx.Document(docx_path)
    except Exception as e:
        raise ManuscriptError(f"Could not open manuscript {docx_path}: {e}") from e

    heading_re = _EN_HEADING_RE if lang == "en" else _JA_HEADING_RE

    chapters: dict[int, dict] = {}
    current_number = None
    current_paragraphs: list[str] = []

    def _flush():
        if current_number is not None:
            # trim leading/trailing blank paragraphs, keep internal blanks (paragraph breaks)
            paras = current_paragraphs[:]
            while paras and not paras[0].strip():
                paras.pop(0)
            while paras and not paras[-1].strip():
                paras.pop()
            chapters[current_number]["paragraphs"] = paras

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        m = heading_re.match(text)
        if m:
            _flush()
            num_raw, title = m.group(1), m.group(2).strip()
            current_number = int(num_raw) if lang == "en" else kanji_to_int(num_raw)
            chapters[current_number] = {"title": title, "paragraphs": []}
            current_paragraphs = []
            continue
        if current_number is not None:
            current_paragraphs.append(_paragraph_text(paragraph))

    _flush()
    return chapters


def chapter_text(chapter: dict, include_title: bool = True) -> str:
    body = "\n\n".join(p for p in chapter["paragraphs"] if p.strip())
    if include_title and chapter.get("title"):
        return f"{chapter['title']}\n\n{body}"
    return body


def word_count(text: str) -> int:
    return len(text.split())


def char_count(text: str) -> int:
    """CJK char count: strip whitespace, count remaining characters."""
    return len(re.sub(r"\s+", "", text))
