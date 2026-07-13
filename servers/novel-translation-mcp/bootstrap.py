"""
bootstrap.py — one-time-per-project setup, NOT an MCP tool. This is for
seeding a project (usually RxR, the one that already had chapters translated
elsewhere) that has pre-existing translated chapters sitting in a separate
manuscript. For a brand-new novel with no prior translation, just call the
`register_project` MCP tool instead — there's nothing to seed.

Run this once (from this folder, with the server's venv active) to:

  1. Register the project in projects.json (idempotent — safe to re-run).
  2. Split the existing JA master docx into per-chapter translations/ja/chNN.txt
     files (chapters already translated and published elsewhere are marked
     "approved" — they're not up for revision by this MVP, just queryable).
  3. Seed the approved glossary from TRANSLATION-LESSONS.md §1.1's core
     terminology table (already human-decided; re-proposing these would be
     pointless busywork).
  4. Leave any chapter with no existing JA text as "not_started".

Safe to inspect before running: it only writes inside STATE_DIR (translations/
+ translation_state.json) and projects.json, and never touches the source docx
files. Step 2 refuses to run if translation_state.json already exists, to
avoid clobbering real progress — delete it first (or pass --force) if you
really want to re-seed. Project registration (step 1) always runs, since it's
idempotent and safe to repeat.
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manuscript
import state
import projects

DEFAULT_EN_MANUSCRIPT = (
    r"C:\Users\Tomoy\Documents\Stories (Mine)\Reincarnator x Regressor I inadvertently "
    r"interfered with the Villainess's second chance at life\Reincarnator x Regressor I "
    r"inadvertently interfered with the Villainess's second chance at life draft 2.docx"
)
DEFAULT_JA_MASTER = (
    r"C:\Users\Tomoy\Documents\Stories (Mine)\Reincarnator x Regressor I inadvertently "
    r"interfered with the Villainess's second chance at life\転生者×回帰者："
    r"うっかり悪役令嬢の第二の人生に干渉してしまった件.docx"
)

# From TRANSLATION-LESSONS.md §1.1 — already-settled decisions, not proposals.
CORE_GLOSSARY = [
    ("reincarnator", "転生者", "Standardized genre term; kanji is the convention (not katakana)"),
    ("regressor", "回帰者", "Less common than 転生者 but recognized; familiar via Korean manhwa influence"),
    ("villainess", "悪役令嬢", "The genre term. Non-negotiable"),
    ("geas", "誓約(ゲアス)", "Ruby gloss on kanji; ゲアス preserves the fantasy loanword"),
    ("runes", "文字(ルーン)", "Gikun-style ruby: kanji carries meaning, katakana carries reading"),
    ("warlock", "邪術師", "魔導師 collides with honorable 魔導 (used for 魔導公爵); explicitly dark"),
    ("witch", "魔女", "Standard"),
    ("buff (magic)", "強化魔法(バフ)", "Ruby gloss; バフ is the gamer term the protagonist thinks in"),
    ("calamity (in-world)", "災禍", "過進 is a hallucinated non-word; 禍進 is a Bleach coinage, in-character only"),
    ("target (practice dummy)", "的", "ターゲット clashes with medieval-fantasy register"),
    ("walkthrough / strategy guide", "攻略情報", "Native concept, lands perfectly"),
    ("level up / XP", "経験値", "The 経験値/経験 pun works natively"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en-manuscript", default=DEFAULT_EN_MANUSCRIPT)
    ap.add_argument("--ja-master", default=DEFAULT_JA_MASTER)
    ap.add_argument("--state-dir", default=None, help="defaults to the EN manuscript's folder")
    ap.add_argument("--project-slug", default="rxr")
    ap.add_argument("--project-name", default="Reincarnator x Regressor")
    ap.add_argument("--force", action="store_true", help="re-seed even if state file exists")
    args = ap.parse_args()

    state_dir = args.state_dir or os.path.dirname(args.en_manuscript)
    state_path = os.path.join(state_dir, state.STATE_FILENAME)

    slug, entry = projects.register(
        name=args.project_name, manuscript=args.en_manuscript,
        source_lang="en", state_dir=state_dir, slug=args.project_slug,
    )
    print(f"Registered project '{slug}' -> {entry['manuscript']}")

    if os.path.isfile(state_path) and not args.force:
        print(f"{state_path} already exists — skipping seeding (already done). Pass --force to re-seed.")
        return 0

    print(f"Parsing EN source: {args.en_manuscript}")
    en_chapters = manuscript.parse_chapters(args.en_manuscript, "en")
    print(f"  found {len(en_chapters)} chapters: {sorted(en_chapters)}")

    print(f"Parsing JA master: {args.ja_master}")
    ja_chapters = manuscript.parse_chapters(args.ja_master, "ja")
    print(f"  found {len(ja_chapters)} chapters: {sorted(ja_chapters)}")

    data = {"schema": 1, "chapters": {}, "glossary": {"approved": [], "staged": []}}

    ja_dir = os.path.join(state_dir, "translations", "ja")
    os.makedirs(ja_dir, exist_ok=True)

    for number, chapter in sorted(en_chapters.items()):
        rec = state.chapter_record(data, number)
        rec["title_en"] = chapter["title"]
        if number in ja_chapters:
            text = manuscript.chapter_text(ja_chapters[number], include_title=False)
            rel = f"translations/ja/ch{number:02d}.txt"
            path = os.path.join(state_dir, rel)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            state.set_translation_status(data, number, "ja", "approved", rel)
            print(f"  ch{number:02d}: JA found ({manuscript.char_count(text)} chars) -> approved, wrote {rel}")
        else:
            print(f"  ch{number:02d}: no JA yet -> not_started")

    for term, translation, note in CORE_GLOSSARY:
        data["glossary"]["approved"].append({"term": term, "translation": translation, "note": note})

    state.save(state_dir, data)
    print(f"\nWrote {state_path}")
    print(f"Seeded {len(CORE_GLOSSARY)} approved glossary terms from TRANSLATION-LESSONS.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
