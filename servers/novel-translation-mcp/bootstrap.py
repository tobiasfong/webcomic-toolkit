"""
bootstrap.py — one-time-per-project setup, NOT an MCP tool. For a novel that
already has a real master docx in more than one language (like RxR: an EN
draft and a JA master that's already 18 chapters in), this just registers
both — get_chapter/search_manuscript then read each language directly from
its own docx, so there's nothing to "seed" as export files anymore (an
earlier version of this script split the JA master into translations/ja/
export files; that's obsolete now that the JA master is read directly, and
those old exports are stale duplicates that should be removed — see
retire_stale_exports() below).

For a brand-new novel with no prior translation at all, don't bother with this
script — just call the `register_project` MCP tool with a single-language
`manuscripts` map.

This also seeds the approved glossary from TRANSLATION-LESSONS.md §1.1's core
terminology table (already human-decided; re-proposing these would be
pointless busywork). Safe to re-run: registration is idempotent, and glossary
seeding skips terms already present (by `term` key) instead of duplicating them.
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


def seed_glossary(state_dir: str) -> int:
    data = state.load(state_dir)
    existing_terms = {t["term"] for t in data["glossary"]["approved"]}
    added = 0
    for term, translation, note in CORE_GLOSSARY:
        if term in existing_terms:
            continue
        data["glossary"]["approved"].append({"term": term, "translation": translation, "note": note})
        added += 1
    state.save(state_dir, data)
    return added


def retire_stale_exports(state_dir: str, lang: str) -> list[str]:
    """Remove translations/<lang>/*.txt export files now that `lang` is read
    directly from its own master docx. These files were pure derived copies
    (split out of that same docx) — deleting them loses nothing that isn't
    already in the master, and leaving them around is a stale-duplicate risk
    for anyone reading the folder by hand."""
    tdir = os.path.join(state_dir, "translations", lang)
    removed = []
    if os.path.isdir(tdir):
        for fname in os.listdir(tdir):
            if fname.endswith(".txt"):
                os.remove(os.path.join(tdir, fname))
                removed.append(fname)
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en-manuscript", default=DEFAULT_EN_MANUSCRIPT)
    ap.add_argument("--ja-master", default=DEFAULT_JA_MASTER)
    ap.add_argument("--state-dir", default=None, help="defaults to the EN manuscript's folder")
    ap.add_argument("--project-slug", default="rxr")
    ap.add_argument("--project-name", default="Reincarnator x Regressor")
    args = ap.parse_args()

    state_dir = args.state_dir or os.path.dirname(args.en_manuscript)

    slug, entry = projects.register(
        name=args.project_name,
        manuscripts={"en": args.en_manuscript, "ja": args.ja_master},
        source_lang="en",
        state_dir=state_dir,
        slug=args.project_slug,
    )
    print(f"Registered project '{slug}':")
    for lang, path in entry["manuscripts"].items():
        chapters = manuscript.parse_chapters(path, lang)
        print(f"  {lang}: {len(chapters)} chapters -> {path}")

    removed = retire_stale_exports(state_dir, "ja")
    if removed:
        print(f"\nRetired {len(removed)} now-stale JA export file(s) (superseded by reading the master docx directly):")
        for fname in sorted(removed):
            print(f"  translations/ja/{fname}")

    added = seed_glossary(state_dir)
    print(f"\nSeeded {added} new approved glossary term(s) from TRANSLATION-LESSONS.md (skipped any already present).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
