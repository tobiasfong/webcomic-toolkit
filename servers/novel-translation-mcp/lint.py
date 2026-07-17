"""
lint.py — deterministic, non-model mechanical checks on Japanese prose.

TRANSLATION-LESSONS.md, cited throughout, is the private requirements log from
the translation project this server was built for — not shipped in this repo.
The specific rules below (kanji-over-kana choices, the non-word watchlist, the
僕-density target) are that project's house style: edit them to match yours.

Why this exists as code and not a model instruction: TRANSLATION-LESSONS.md
§2.7 documents a repeated failure mode called "verification theater" — asked
to "check the chapter," a model runs a regex-shaped scan, finds it clean, and
reports as though it had also READ the prose. It hadn't. Moving the mechanical
half of that work into actual code removes the temptation to substitute a scan
for a read: the scan runs here, silently, and its output is one INPUT to a
human/model review — never a replacement for one.

This module is intentionally narrow. It catches:
  - orthography violations of this project's LOCKED kanji-over-kana rules
  - unbalanced brackets + the "drop 。before ）" punctuation rule
  - a hardcoded watchlist of confirmed non-words/bad compounds (grows over time)
  - Latin-script leakage (likely un-translated English)
  - 僕 pronoun density (the one metric TRANSLATION-LESSONS.md §2.2 gives a
    numeric target for)

It does NOT catch meaning-flips, register drift, wordplay adaptation, or
anything else that requires actually understanding the sentence — those need
a real read (see §2.7, §2.3-2.9). Never let a clean lint result substitute for
that.
"""

import re

_TACHI_EXCEPTIONS_PREFIX = "か"  # かたち
_TACHI_EXCEPTION_PHRASE = "たちどころに"

_NONWORD_WATCHLIST = {
    "過進": "not a real word — use 災禍 (禍進 is a Bleach coinage, in-character reference only)",
    "熱血気盛ん": "not a real compound — 熱血 and 血気盛ん are separate expressions",
    "魔男": "not a real word",
    "神経に触れる": "not standard — use 癪に障る or 気に障る",
    "昂ぶりが積み上がる": "translationese calque of 'anticipation built' — consider 期待が膨らむ",
    "凍りついた頭が": "translationese calque of 'my frozen mind' — consider 強張った思考が",
}

_BRACKET_PAIRS = [("「", "」"), ("『", "』"), ("（", "）")]


def _excerpt(text: str, i: int, radius: int = 20) -> str:
    start = max(0, i - radius)
    end = min(len(text), i + radius)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def check_orthography(text: str) -> list[dict]:
    """達/たち, 何故/なぜ, 貴方・貴女/あなた — locked project conventions
    (TRANSLATION-LESSONS.md §1.2). Flags only; never rewrites."""
    findings = []

    for m in re.finditer("たち", text):
        i = m.start()
        if text[max(0, i - 1):i + 2] == _TACHI_EXCEPTIONS_PREFIX + "たち":
            continue
        if text[i:i + len(_TACHI_EXCEPTION_PHRASE)] == _TACHI_EXCEPTION_PHRASE:
            continue
        findings.append({
            "category": "orthography",
            "detail": "たち should be 達 (locked rule; exceptions: かたち, たちどころに)",
            "position": i,
            "excerpt": _excerpt(text, i),
        })

    for m in re.finditer("なぜ", text):
        i = m.start()
        findings.append({
            "category": "orthography",
            "detail": "なぜ should be 何故 (locked rule)",
            "position": i,
            "excerpt": _excerpt(text, i),
        })

    for m in re.finditer("あなた", text):
        i = m.start()
        findings.append({
            "category": "orthography",
            "detail": "あなた should be 貴方 or 貴女 in kanji (locked rule — pick per speaker)",
            "position": i,
            "excerpt": _excerpt(text, i),
        })

    return findings


def check_brackets(text: str) -> list[dict]:
    """Unbalanced 「」『』（） + the 'drop 。before ）' punctuation rule
    (TRANSLATION-LESSONS.md §1.5, §3.1.6)."""
    findings = []

    for open_c, close_c in _BRACKET_PAIRS:
        depth = 0
        for i, ch in enumerate(text):
            if ch == open_c:
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth < 0:
                    findings.append({
                        "category": "bracket",
                        "detail": f"Unmatched closing {close_c!r} (no corresponding {open_c!r})",
                        "position": i,
                        "excerpt": _excerpt(text, i),
                    })
                    depth = 0
        if depth > 0:
            findings.append({
                "category": "bracket",
                "detail": f"{depth} unclosed {open_c!r}",
                "position": None,
                "excerpt": None,
            })

    for m in re.finditer("。）", text):
        i = m.start()
        findings.append({
            "category": "bracket",
            "detail": "remove the 。 before ） (rule: drop final 。 before internal-thought bracket; keep ！？)",
            "position": i,
            "excerpt": _excerpt(text, i),
        })

    return findings


def check_nonword_watchlist(text: str) -> list[dict]:
    """Hardcoded list of confirmed hallucinated/non-standard strings caught in
    past chapters (TRANSLATION-LESSONS.md §3.2). Append to _NONWORD_WATCHLIST
    as new ones are confirmed — this is a growing list, not a fixed one."""
    findings = []
    for phrase, note in _NONWORD_WATCHLIST.items():
        for m in re.finditer(re.escape(phrase), text):
            i = m.start()
            findings.append({
                "category": "nonword",
                "detail": f"'{phrase}' — {note}",
                "position": i,
                "excerpt": _excerpt(text, i),
            })
    return findings


def check_latin_leakage(text: str) -> list[dict]:
    """Runs of 2+ Latin letters — likely un-translated English left in by
    accident. Over-flags on purpose (e.g. intentional loanwords in Latin
    script); this is a flag for human judgment, not an auto-fix."""
    findings = []
    for m in re.finditer(r"[A-Za-z]{2,}", text):
        i = m.start()
        findings.append({
            "category": "latin_leak",
            "detail": f"Latin-script run {m.group(0)!r} — check for un-translated English",
            "position": i,
            "excerpt": _excerpt(text, i),
        })
    return findings


def check_pronoun_density(text: str, pronoun: str = "僕") -> dict:
    """TRANSLATION-LESSONS.md §2.2: measured target ~0.3-0.6 per 100 chars for
    僕; above ~0.7 warrants review (multi-party scenes may legitimately run
    higher — this is a flag, not a verdict)."""
    stripped = re.sub(r"\s+", "", text)
    n = len(stripped)
    count = stripped.count(pronoun)
    density = (count / n * 100) if n else 0.0
    flagged = density > 0.7
    return {
        "pronoun": pronoun,
        "count": count,
        "char_count": n,
        "density_per_100_chars": round(density, 3),
        "flagged": flagged,
        "note": ("Above ~0.7/100 chars — review for over-use; multi-party scenes may legitimately run higher."
                  if flagged else None),
    }


def lint(text: str) -> dict:
    """Run every mechanical check and return a single findings list plus the
    pronoun density metric. This is the whole point of the module: one call,
    deterministic, silent-until-asked-for — never presented as a substitute
    for actually reading the chapter."""
    findings = []
    findings += check_orthography(text)
    findings += check_brackets(text)
    findings += check_nonword_watchlist(text)
    findings += check_latin_leakage(text)
    findings.sort(key=lambda f: (f["position"] is None, f["position"]))
    return {
        "finding_count": len(findings),
        "findings": findings,
        "pronoun_density": check_pronoun_density(text, "僕"),
    }
