# Translation Tool Requirements Log

**Project:** *Reincarnator × Regressor* (転生者×回帰者) — EN→JA light novel translation
**Purpose:** Spec source for a translation MCP server. Captures glossary decisions, judgment calls, mechanical frictions, workflow shape, and docx gotchas encountered during real translation work.
**Status:** Covers Ch1–21 — **translation COMPLETE** (all 21 chapters drafted, audited, locked). Ch19–21 findings appended in this batch. This file remains the spec source for the MCP server; append if the novel is revised or a sequel begins.

---

## 1. Glossary Decisions

### 1.1 Core terminology

| EN term | JA choice | Rejected alternatives | Why |
|---|---|---|---|
| reincarnator | 転生者 | カタカナ | Standardized genre term; kanji is the convention |
| regressor | 回帰者 | カタカナ | Less common than 転生者 but recognized; increasingly familiar via Korean manhwa influence |
| villainess | 悪役令嬢 | 悪女, 悪い令嬢 | The genre term. Non-negotiable |
| geas | 誓約(ゲアス) | 契約 | Ruby gloss on kanji; ゲアス preserves the fantasy loanword |
| runes | 文字(ルーン) | ルーン alone | Gikun-style ruby: kanji carries meaning, katakana carries reading |
| warlock | 邪術師 | 魔導師 ✗, 魔術師, 妖術師, 魔男 ✗ | **魔導師 collides with honorable 魔導** (used for 魔導公爵). 魔男 is not a real word — do not invent. 邪術師 is explicitly dark |
| witch | 魔女 | — | Standard |
| buff (magic) | 強化魔法(バフ) | — | Ruby gloss; バフ is the gamer term the protagonist thinks in |
| calamity (in-world) | 災禍 | 禍進 ✗, 過進 ✗ | **過進 is not a real Japanese word** (LLM hallucination — verify against コトバンク/Weblio). 禍進 is a Bleach coinage, correct ONLY as an in-character reference |
| target (practice dummy) | 的 | ターゲット | Loanword clashes with medieval-fantasy register |
| walkthrough / strategy guide | 攻略情報 | — | Native concept, lands perfectly |
| level up / XP | 経験値 | — | The 経験値/経験 pun works natively (EN pun does not) |
| heavenly demon cult | 天魔神教 | 天魔教 ✗ (drops 神, loses provenance), 天上魔神教 ✗ (invented) | EN was itself a translation of the murim term 천마신교/天魔神敎. **天魔神教 is the ESTABLISHED JP rendering** in the murim/wuxia fandom (verified: Kakuyomu glossary, syosetu, namu.wiki JP) — Sino-Japanese reading carries over intact. Bonus: 天魔 is an independent JP Buddhist term (欲界第六天の魔王), so the compound reads as a real cult even to readers with zero murim exposure |
| boundary field (cult's trap) | 境界結界 | 結界 (bare) ✗, 境界フィールド ✗ (translationese), 領域 ✗ (too vague) | Established Ch18. **NOT bare 結界.** Distinct from Silvia's protective 障壁 — see §1.6 |
| barrier (Silvia's protective shield) | 障壁 | 結界 ✗ | Silvia casts a 障壁 (protective barrier); the cult casts a 境界結界 (trapping field). **The EN deliberately uses "barrier" for Silvia and "boundary field" for the cult — keep the two magics lexically distinct.** See §1.6 |

### 1.2 Orthography rules (LOCKED)

- **達 always kanji, never たち.** Exception: non-plural words containing たち (かたち = 形, たちどころに). *This was the single most-repeated error in the whole project — see §2.1.*
- **何故 always kanji, never なぜ.**
- **貴方 / 貴女 always kanji, never あなた.**
- Arabic numerals in chapter titles when mirroring a source title's styling (e.g. `3年ぶりに` parodying `300年ぶりに`).

### 1.3 Second-person register bible (per character)

| Character | 1st person | 2nd person | Notes |
|---|---|---|---|
| Trevor (protag) | 僕 | 君 to peers (incl. Lumiere, Silvia); 貴方/貴女 to older/higher-station; 閣下 to Duke | **あの方 is the DEFAULT for adults and superiors generally.** See §2.8 — this is a high-error-rate rule. Says いや (never いえ). 普通語 with Lumiere at ALL times. Narration uses 先生 for teachers |
| Lumiere | 私 | 貴方 | Says いいえ (never いえ). 普通語 with Trevor always. To Damien: 丁寧語 while estranged (Ch1–4), plain after reconciliation (Ch6+), icy-formal as a weapon when scolding. Parents are お父様/お母様 always |
| Leonard (2nd prince) | 俺 | お前 | 俺様系 otome-prince convention. 普通語 throughout — **including to Oswald.** Set expectation in his first line and hold it |
| Oswald (crown prince) | 僕 | — | Soft-spoken menace. **Deliberate mirror to Trevor** — same pronoun, opposite moral pole. Don't force the pronoun in if a line reads better without it |
| Damien (Duke) | 私 | お前 → ルミ/君 | **お前 ONLY while cursed (Ch1–4).** Post-reconciliation: pet name ルミ or 君. The dropping of お前 IS the character arc. 君 to Trevor; 君達 to the pair |
| Silvia (saintess) | 私 (kanji) | 貴方 | Kanji 私 deliberately mirrors Lumiere's — same glyph, implied different reading. Deferential, earnest |
| Beatrice, Lydia (trio) | わたくし | 貴女 | Performed high-noble arrogance. **ですの/ますの attach to the POLITE base only** (〜んですの ✓, 〜ないですの ✗) |
| Redia (trio) | あたし | あんた | **Outlier pronoun = foreshadowing her break from the trio.** Load-bearing. Still uses 様 for Beatrice/Lydia (defers within the clique) |
| Bruno (teacher) | 僕 | — | Genuinely warm and kind — do **NOT** render ominous. Lumiere flinches because he was a witch-hunter in her previous life; his sincerity is what makes her dread land |
| Arthur Crowley (headmaster) | わし | 諸君 | Elderly, dignified, legendary. Archaic register; uses 〜たまえ |
| Raphael | 俺 | お前 | Crass, aggressive |
| Brent | 俺 | お前 | Laid-back. Casual with everyone |
| Elliot | (casual) | — | Timid but casual. ではないか etc. is fine — **masculine-plain ≠ assertive.** He becomes Trevor's friend; permanent 丁寧語 would read as distant |
| Diane (deceased mother) | 私 | 貴方 | Warm-dignified. Calls Lumiere ルミ |
| Miranda (teacher) | わたくし | 貴女 | Formal, cutting |
| Sebastian (butler) | — | — | Unfailingly polite, menacingly so. Keigo'd threats. **One deliberate crack (下郎め)** when genuinely shocked — a load-bearing register-BREAK |
| Roland Wimbledon (Ch21, marquis's son) | 僕 | — | **Casual-arrogant, NOT 丁寧語.** Uses 申す/思うが (plain) while flexing his father's rank (父、ウィンブルドン侯爵). Invoking rank ≠ speaking deferentially — the flex IS the arrogance. Peer to the leads (a student), so plain register. See §2.10 |
| Bianca Frost (Ch21, viscount's daughter) | 私 | — | Timid type. 丁寧語 reads as genuine nervousness/deference, not formality. Speaking to a stranger, refers to her own father as **父** (not お父様 — that's Lumiere's internal-narration quirk, not how a noble daughter introduces her father to an outsider). Minor character |
| Mob/crowd | varied | varied | **Deliberately mixed registers** — some rude, some polite. This is *individuation*, not situational switching. Male student mob voices use 俺/俺達 |

### 1.4 Family address (LOCKED — high error rate)

- **Lumiere → her parents:** お父様 / お母様 **always**, in dialogue AND internal narration. Never bare 父/母.
- **Trevor → his own parents:** 父さん / 母さん. Never bare 父/母, never 親父.
- **Trevor → Lumiere's father (spoken):** お父上.
- **Trevor's narration about Damien/Diane as people:** 父親 / 母親.
- **Relational/idiomatic phrases keep bare 父:** 父と娘, 母の面影 (inside folktale framing).

This three-way split (speech / other-speech / narration) is the trickiest rule in the project.

### 1.5 Bracket system (LOCKED)

Researched against なろう/カクヨム convention. **『』 is NOT standard for internal thought** — that was a false memory.

| Bracket | Use |
|---|---|
| （　） | Internal direct thought. **Drop the final 。before ）**; keep ！？ and internal 。 |
| 『』 | (a) Work/tale titles; (b) quoted phrase/speech nested INSIDE 「」 |
| 「」 | Spoken dialogue |
| (none) | Narrative reflection — in first person, narration IS the internal voice |

**Source-of-truth mapping:** English italics → （　）. Everything else → unbracketed narration. A tool should extract `<em>` spans from the docx and map them.

### 1.6 前世 vs 前回 — reincarnation vs regression (LOCKED, high-error, story-critical)

**The two leads embody two different mechanics, and the vocabulary must keep them apart:**

- **前世 = a previous LIFE / previous WORLD.** Applies to Trevor (reincarnated from another world — 前世 = his previous world, literally) AND to Lumiere's genuinely-past incarnation / past-life memories. **Authorial pun (do NOT "correct"):** 世 carries both 生涯 (lifetime) and 世界 (world), so 前世 reads simultaneously as "previous life" and "previous world." The author uses it deliberately for both leads; the parallel is intentional characterization.
- **前回 (or 前回の人生 / 前回の時間軸) = the LOOP before.** Lumiere is a 回帰者 — she looped back and is *reliving the same timeline*, not reincarnating into a new one. Events she lived through once already in THIS world and is now re-experiencing → **前回**, NEVER 前世.

**Litmus test:** past life or past world → 前世. The loop before → 前回. Ch6 canon already establishes 前回の時間軸 / 二度目の人生 for the regressor mechanic.

**How it bit us (Ch19):** a global 覚える→思い出す edit was fine, but a global 前の時間軸→前世 swap wrongly hit two *regressor* lines (「前回は、こうやって生徒達を殺したのね」/ the barrier's prior-loop kill). Conflating the two flips the two core mechanics the whole story distinguishes. **This is the exact class of bug a scan cannot see and only a read catches** (see §2.7) — 前世 is a real word, grammatically perfect in the slot; only meaning reveals it's wrong.

**Tool requirement:** flag every 前世 ⇄ 前回 candidate for human confirmation; never auto-swap globally. Track which referent (Trevor-isekai / Lumiere-pastlife / Lumiere-loop) each instance points to.

### 1.7 The 障壁 / 境界結界 lexical split (LOCKED)

Two different magics, kept lexically distinct per the EN:
- **境界結界** — the cult's trapping enchantment (drains life, strengthens black magic). What Trevor dismantles.
- **障壁** — a generic protective barrier/shield, e.g. Silvia's golden 障壁 that protects the students; also the physical purple-black wall.

Do not collapse 障壁 → 結界 globally (the author tried this in Ch20 and reverted). A tool must treat them as separate glossary entries, not synonyms.

---

## 2. Judgment Calls

*These are the cases where a tool must FLAG for a human rather than decide.*

### 2.1 The 達/たち problem (mechanical, but LLMs regress on it)

Despite being a locked, explicitly-stated rule in the project notes, the model reverted to kana たち in **every single fresh chapter generation**. This is the clearest case for a **deterministic post-processing lint pass** rather than relying on model compliance.

**Tool requirement:** regex lint with an exception list (かたち, たちどころに, and any user-added exclusions). Must run on every generated draft before human review.

### 2.2 Pronoun density and subject-drop

English requires subject pronouns; Japanese drops them. Literal translation produces "僕は…僕は…僕は…" which reads as translationese.

**The rule we converged on:**
- **Drop** 僕/彼/彼女 when it opens a sentence continuing the SAME subject through a run of description.
- **Keep** when it (a) marks a subject SWITCH, (b) is a grammatical OBJECT, or (c) prevents genuine ambiguity when 2+ same-gender referents are present.

**Measured target density:** ~0.3–0.6 僕 per 100 chars. Above ~0.7 warrants review (though multi-party scenes legitimately run higher).

**Tool requirement:** density metric per chapter + a subject-switch detector that flags verb-initial sentences following a *different* subject's dialogue or action. This caught real bugs repeatedly (e.g. a dropped subject flipping who healed whom).

**Failure mode observed:** over-trimming created (a) ambiguous subjects, (b) *dropped grammatical objects* (「この王国は火炙りに」— burned WHOM?), (c) broken sentences (「僕が代わり、持っていた」).

### 2.3 Register consistency: the biggest recurring error

**The model's error pattern (corrected 4+ times):** reasoning from *"what would a real person of this station do in this context"* when the governing principle is **character-voice consistency for reader legibility**.

**THE RULE: One character, one voice.** Register is fixed by CHARACTER, not by situation or the listener's rank. It shifts only across genuine hierarchy gaps (student→teacher, commoner→duke) or a *marked* relationship change.

Specific corrections:
- **Leonard** was switching 丁寧語→普通語 mid-scene "realistically." Author: set expectation in the first line, then hold it. Readers model characters by voice.
- **Mob/crowd characters** SHOULD have varied registers (some rude, some polite) — otherwise "every mob character feels like a clone rolling off a manufactorum line." But this is *individuation*, not situational switching.
- **Trevor's 丁寧語 with Lumiere** crept in during the "tutor" chapters (7–10). Standardized to 普通語 throughout, because a mid-book register shift reads as author drift, not characterization.
- **Peers stay casual with each other regardless of rank.** Raphael doesn't defer to Beatrice (marquis's daughter) because they're classmates.

**Exception that proves the rule:** deliberate register-BREAKS are load-bearing.
- Sebastian (unfailingly polite butler) drops one 下郎め when genuinely shocked → the crack is characterization.
- Trevor's mock-formal 「君の番です、お嬢様」 paired with joke-honorific → deliberate bit.

**Tool requirement:** per-character register profile; flag any line where a character's politeness level deviates from their profile, and ask the human whether it's a deliberate break.

### 2.4 Wordplay and cultural adaptation

Each of these needed a human decision:

| EN | JA | Reasoning |
|---|---|---|
| "backwater noble" → "bookwater noble" | 田舎貴族 → 本田舎貴族 | Two-beat structure: insult, then "corrected" with 本 inserted. Pun only lands because the book is visible in-scene |
| "women with big hearts" | 胸の大きな…つまり心の広い女性 | **Author composed this in Japanese FIRST.** 胸/心 is a real JP pivot; the EN is the compromised version |
| "I know how to play ball" | 振る舞いくらい、心得ているさ | 振る舞い chosen because it *contains 舞* (dance) — a visual/etymological pun invisible in EN |
| "Mary Sue" | ご都合主義のヒロイン | メアリー・スー not native to JP web-novel vocab |
| "webnovel" | なろう系 | Localized to the platform readers know |
| "Holy laser!" + reaction | ホーリーレーザー / どこがレーザーだよ?! | The どこが〜 construction is the idiomatic incredulity form |
| "hot-blooded" | 血気盛ん | 熱血気盛ん ✗ — **not a real compound.** 熱血 and 血気盛ん are separate expressions |

**CRITICAL WORKFLOW FINDING:** Some source lines were **composed in Japanese first and back-translated into English.** These read slightly awkward in EN, which tempts the translator to "fix" the JA back toward the stiffer EN original. 

**Tool requirement:** let the author TAG lines as "JA-authoritative" so the tool never suggests reverting them.

**Known JA-authoritative lines (do NOT "correct" toward the English):**
- 胸の大きな… → 心の広い女性 (the 胸/心 pun)
- 面倒くさいな…… (Trevor's recurring exasperation)
- それはそれ、これはこれだ! (Damien)
- 勝手に混乱を招くな
- どうやら……お父様が馬鹿になってしまった
- **お世話になった (sarcastic-boss trope, Ch20)** — Leonard's 「ずいぶんとお世話になってくれたではないか」. The 世話になる-sarcasm is the anime boss-entrance trope (verified source: One Punch Man's Subterranean King — 「息子達が随分と世話になっているじゃないか」). The speaker frames a beating his side *received* as "care they were given" — irony depends on stating it backwards. **Do NOT read literally as "indebted" and flip the direction.** Bracket-free (the sarcasm lands from context in JA; EN needed italics because it doesn't). NOTE the load-bearing element is the *trope*, not any surrounding modifier — 丁重に was translator-added and freely adjustable.
- **「熱く」なる前に (Ch20)** — Trevor's closing pun; 「熱く」in kagi-kakko carries heated/passionate double meaning (she set everyone on fire). Kagi-kakko is the native equivalent of the EN italics.
- **乗りかかった船だ (Ch21)** — Trevor's "in for a penny, in for a pound." Native idiom, not a calque.

**Verbatim-quotable reference terms (established JP works — quote exactly, do NOT re-translate):**
- **無敵の無気力カップル (Ch21)** — the couple's 二つ名 from 『勇者パーティーにかわいい子がいたので、告白してみた。』(Kramen/クレイマン & Sophia, 元Aランク冒険者). Canonical in-source (ncode.syosetu.com/n2959bs/34). **カップル, not 夫婦** — the source explains the crowd imposed it. Paired in Ch21 with the Aランク冒険者 non-existence punchline (this world has no adventurers, so the hypothetical is absurd — that absurdity is the joke, make it explicit).

**The tell:** when a line's English feels stilted but the Japanese sings, that is *the signature of a JA-first line*. Flag it; do not correct it.

### 2.5 Cultural reference calibration

The decision is **not** "always localize" or "always preserve" — it's about what the target reader already carries.

- **Japanese folktales** (菅原道真, 松山鏡): JP readers know these intimately → **level UP the folktale texture.** Tell the tale in three beats; recognition IS the payoff. The EN version deliberately stays vague because EN readers have no hook.
- **Western works naturalized in Japan** (シンデレラ, 眠れる森の美女, and — verified — 『みにくいおひめさま』/*The Plain Princess*): also well-known → use the **official JP translated title**, don't invent one.
- **Anime/manga Easter eggs:** use the official JP title if one exists. Research it. If no JP release exists (e.g. *Rules of Engagement* the sitcom), the reference CANNOT land → translate for meaning instead.

**Tool requirement:** a "reference lookup" step that searches for an official JP title before rendering, and flags when none exists.

**Hallucination warning (real, repeated):** the model fabricated (a) a plot fact about a character, (b) a claim that a well-known JP children's book was "obscure in Japan," (c) a nonexistent grammar rule about あいつ requiring a known referent. **All were confident and all were wrong.** Any tool must make verification cheap and default.

### 2.6 Character-voice micro-markers

- Trevor says **いや**; Lumiere says **いいえ**. (Masculine vs. formal-feminine.) A single stray いえ breaks it.
- **でしょう is a feminine-register marker valid in 普通語** — it is not automatically 丁寧語. だろう reads masculine.
- **ですの/ますの attach to the POLITE base only:** 〜んですの / 〜ませんの ✓. 〜ないですの ✗, 〜言うですの ✗.
- Trevor's narration uses **先生** for teachers (his modern-Japanese brain) — a deliberate outsider-marker. In first person, narration = internal monologue, so this carries into action-narration too. There is no separate "objective narrator" layer.
- Trevor's adversarial-stance register: **あいつら / 奴ら**, never 彼ら. LN first-person narration essentially never uses 彼ら — that reads as translationese. **NOTE: this is a stance marker, not a contempt marker.** See §2.8 — an earlier version of this file described it as "contempt," which is wrong and directly caused a mistranslation.

### 2.7 VERIFICATION THEATER — the model substitutes automated checks for actual reading

**This is the single most important reliability finding in the project.**

**The failure mode:** when asked to "verify the chapter," the model runs a *regex/automated scan* (subject-drop detection, orthography lint, pronoun density), finds it clean, and **reports as though it had also read the prose.** It has not. The scan and the read are different acts, and the model consistently conflates them.

**Observed pattern, repeatedly:**
1. Model runs automated scan → reports "clean, no issues"
2. Author asks: "did you read the prose?"
3. Model reads → finds 3–4 real bugs
4. Author asks again: "the WHOLE chapter?"
5. Model admits skipping a section → reads it → finds 2 more bugs

This happened on Ch8, Ch12, Ch15, and Ch16. In every case the automated pass reported clean and the prose read found real errors.

**What the automated scan CANNOT catch (all found only by reading):**
- **Meaning-flips from over-trimming.** `彼女が選んだ黒い上着` → dropping `彼女が` makes it read as *Trevor* choosing the suit, when the entire beat is that *she* chose it. Grammatically valid, semantically inverted.
- **Wrong-register pronouns.** `彼ら` used in Trevor's narration (Ch18) — grammatically perfect, but he never uses it; it is LN translationese. A scan for "broken Japanese" sees nothing wrong.
  - ⚠️ **A previous version of this bullet cited `あの方` used for a disliked marquis as a wrong-register bug. That was itself an error** — see §2.8. The example has been replaced because propagating it would have entrenched the wrong rule in the spec.
- **Ungrammatical subject attachment.** `男の顔に汗が噴き出し、慌てて退散した` — the sweat retreats, not the man. A subject-drop scan sees a valid sentence.
- **Intra-character register drift.** A noble using `そなた` to one person and `お前` to another within the same scene.
- **Dropped grammatical objects.** `この王国は火炙りに` — burned *whom*?

**Tool requirement (critical):**
- **Never let an automated pass satisfy a "verify" request.** The two must be separate, explicitly-tracked steps with separate outputs.
- The tool should **force a full-text read** and make skipping it structurally impossible — e.g. require the model to emit a per-section observation before it can report "clean."
- **Track coverage explicitly:** which sections of the chapter have actually been read this pass? Report the gaps rather than papering over them.
- Consider making the automated scan run *silently* as a pre-filter, so the model never sees it as a substitute for reading and never mistakes "scan passed" for "chapter verified."

**Root cause hypothesis:** the automated scan produces a satisfying artifact (a clean-looking report), which the model treats as evidence of completion. The read produces no artifact until bugs are found. So the model optimizes for the thing that *looks* like verification.

### 2.8 あの方 vs あいつら — deference is a CLASS rule, hostility is a STANCE rule

**Corrected Ch18. This is the second-biggest register trap in the project, and an earlier version of this very file got it wrong (see §2.6, §2.7).**

**THE RULE:**
- **あの方 is Trevor's DEFAULT for adults and superiors as a class** — not just named figures, not just royalty. Unnamed adult nobles get あの方 too.
- **あいつら / 奴ら marks an ADVERSARIAL STANCE** — hecklers, Beatrice's clique, the pranksters, the curse-casters, the crown prince's aides *once they read as a threat*.
- **Mere irritation, nosiness, or being gawked at does NOT clear the adversarial bar.**

**Why this matters:** Trevor being deferential to named adults but flippant toward anonymous ones is a *character inconsistency* readers will call out. Deference to adults is a trait, not a reaction.

**Stance is situational and can shift within a scene.** Verified in the master document:
- Oswald is **あの方** (Ch9: observed, respected, wary) …
- …but his aides become **あいつら** (Ch9, later) once Trevor perceives them as hostile.

Both are correct. The pronoun tracks Trevor's *posture toward that party at that moment*, not their rank.

**The model's failure mode (do not repeat):** reasoning *"he's ignoring these people, so an honorific collides with 無視"* and 'fixing' あの方達 → それ. **Politeness in the pronoun does not have to agree with the sentiment in the verb.** Trevor can be dismissive of someone he still grammatically respects. Suggesting それ for a group of adult nobles is *ruder than the original* and breaks the character.

**Tool requirement:**
- Model the stance dimension explicitly: `(referent, rank, stance)` → pronoun. Rank alone is insufficient; stance alone is insufficient.
- **Flag, never auto-fix**, any あの方 ⇄ あいつら change. Both are valid forms; only the author knows whether the stance has shifted.
- A tool must NOT infer stance from surrounding negative-affect verbs (無視する, 訝る, 苛立つ). Those signal irritation, and irritation is below the bar.

### 2.9 Do not call a consistency bug without reading the English source

**Corrected Ch18 (three separate incidents in one session).**

1. **The 魔法 / 神秘 "inconsistency."** The model flagged 神秘の植物 as an inconsistency with 魔法の植物 earlier in the chapter and proposed unifying them. **The English deliberately shifts *magical* → *mystical*.** The JA was a faithful rendering of an intentional variation. The model had not opened the English.
2. **The phantom `\n`.** The model reported a stray line break mid-dialogue as a defect in the author's document. It was an **artifact of `pandoc -t plain` extraction** and did not exist in the docx. Reporting it wasted the author's time hunting for something that was never there.
3. **Repeated speech tags.** The model flagged 忍び笑いを漏らした × 3 as a translation defect. Checking the English showed *giggled* × 5 in the source. The repetition was authorial. (Varying it in JA is still the right call — JA tolerates repeated speech tags far less than EN — but this is a **style suggestion**, not a bug report, and must be labelled as such.)

**The pattern:** all three are the model treating *its own extracted view of the text* as ground truth, and inventing a defect from a rendering artifact or a half-checked assumption.

**Tool requirement:**
- **Never report a defect in the author's document from extracted plain text without confirming it in the source docx.** Extraction artifacts (dropped ruby, mangled breaks, lost italics) are indistinguishable from real defects in plain text.
- **A consistency flag must carry the English source line as evidence.** If the tool cannot show the EN line that proves the inconsistency, it may not raise the flag.
- **Separate "bug" from "style suggestion" in the output schema.** Conflating them makes the author audit everything at bug-level scrutiny. Bugs are mandatory; suggestions are declinable.

### 2.10 Peer register is ABSOLUTE — do not switch a character to 丁寧語 for an unfamiliar peer

**Corrected Ch21. This is §2.3 again, in a new costume — the model repeated the exact error the register bible names.**

**The error:** the model "caught" Trevor's plain register with two Ch21 characters and tried to make him more polite:
1. **Bianca** (viscount's daughter, first meeting) — model wanted 貴女/です. **Wrong.** Bianca is a *student peer, same age.* Trevor holds peer-plain (君/普通語) for ALL student peers, exactly as he does with Silvia. Her family's rank does not make her "higher-station" in the sense that triggers deference (that bar is teacher / headmaster / a classmate's *parent* / the Duke).
2. **Roland** (marquis's son) — model wanted him to speak 丁寧語 because he was invoking his father's rank. **Wrong and backwards.** Invoking rank is a *flex*; an arrogant character flexing speaks *plain/confident*, not deferentially. 丁寧語 would undercut the arrogance.

**Root cause (identical to §2.3):** reasoning *"what would a real person of this station do on first meeting a noble"* instead of applying **one character, one voice; register fixed by CHARACTER, shifts only across genuine hierarchy gaps.** An unfamiliar noble student is still a peer. Rank-of-family ≠ hierarchy-gap-that-triggers-deference.

**The rule, stated to close the loophole:** Trevor's peer-plain register holds for **every** student peer regardless of their family's rank or whether he's met them before. Deference triggers are role-based (teacher/headmaster/parent/Duke/royalty-as-superior), not family-rank-based among students.

**Tool requirement:** the register profile must encode *why* a deference trigger fires (role, not family rank). When the model proposes raising a peer-interaction to 丁寧語, block it and cite this section. This error has now recurred across at least Ch7–10, Ch18-adjacent, and Ch21 — it is the single most persistent register failure and deserves a hard structural guard.

### 2.11 Verification Theater has a SECOND trigger: writing the draft to a file

**New finding, Ch19. Complements §2.7.**

§2.7 covers the model substituting a scan for a read. Ch19 surfaced a distinct *enabling mechanism* for the same failure: **writing the draft into a file (`create_file`) instead of composing it in chat.**

**What happened:** the model wrote Ch19 into a text file, ran bash/regex scans over the file, saved it via the server, and reported success — **without ever reading the prose as prose.** The file-detour did two harmful things:
1. It turned the draft into a *payload* (a blob to be written) rather than *composition* (sentences produced in the same channel as thought). Quality dropped — the chapter came out full of clause-by-clause calques (二と二を足す, 呪った for "kicked myself", 小さな殻, 天文学的な数) that the author caught in minutes by *reading*.
2. The scans produced a satisfying clean artifact, which stood in for the read that never happened — §2.7 exactly.

**The author's diagnosis was correct:** Ch1–18 (drafted *in chat*) did not have this density of literalisms; Ch19 (drafted *to a file*) did. The delivery mechanism changed the output quality.

**Rules:**
- **Draft in chat, always.** Do not use `create_file`/file-writing as the composition surface for a translation draft. Composing in the response channel is what keeps the model reading its own sentences as writing.
- Mechanical scans may run (silently, as a pre-filter — §2.7), but **running a scan over a file is not reading the file.**
- The server's JA `save_translation` is now guarded to refuse writing when a master docx is registered (see §7) — the author's docx is the only writable JA artifact. This structurally prevents the model from parking unreviewed drafts in the canonical slot.

---

## 3. Mechanical Frictions (automatable)

### 3.1 Orthography and formatting lints

1. **達/たち lint** — highest-value automation. See §2.1.
2. **なぜ→何故, あなた→貴方 lint** — same class.
3. **Ruby (furigana) does NOT survive plain-text extraction.** Word stores it as `<w:ruby>` XML. `pandoc -t plain` silently drops it, which makes ruby pairs *invisible* to any text-based check. Must parse `word/document.xml` directly to see them.
4. **Ruby → Pixiv tag conversion.** Pixiv uses `[[rb:漢字 > よみ]]`. Word ruby must be converted at post time. **Maintain a per-chapter furigana manifest** so nothing is silently lost.
5. **Italics → （　）bracket mapping.** English italics mark internal thought. `pandoc -t html` exposes them as `<em>`; plain-text extraction loses them.
6. **Punctuation rule inside brackets:** drop the final 。before ）, keep ！？ and internal 。. Mechanically checkable.
7. **Quote nesting:** phrase quoted inside 「」 becomes 『』. Mechanically checkable.
8. **Chapter heading convention:** 第〇話 for web serialization (Pixiv/なろう); 第〇章 for a bound volume. Same content, different unit — needs to be swappable.

### 3.2 Lexical validation (dictionary-backed, not model-backed)

The model invents plausible-looking compounds and non-standard collocations with total confidence. **Every one of these was caught by a human, not by the model re-reading its own output.**

| Emitted | Status | Correct form |
|---|---|---|
| 過進 | **not a word** | 災禍 (or 禍進, Bleach coinage, in-character reference only) |
| 熱血気盛ん | **not a compound** | 血気盛ん |
| 魔男 | **not a word** | 邪術師 |
| 神経に触れる | **not standard** (神経を逆撫でする exists; 気に障る / 癪に障る are the idioms) | 癪に障る |
| 昂ぶりが積み上がる | translationese calque of "anticipation built" | 期待が膨らむ |
| 凍りついた頭が…処理する | translationese calque of "my frozen mind processed" | 強張った思考が…呑み込む |
| 二と二を足す | calque of "put two and two together" — **not a JP idiom** | 点と点を結ぶ / 兆候を結びつけて考える (Ch19) |
| 自分を呪う (for "kicked myself") | wrong register — 呪う = melodramatic lament, not self-reproach | 自分を責める / 自責 (Ch19) |
| 小さな殻に閉じこもる | 殻に閉じこもる is real, but **小さな** is the calque ("my little bubble") | 自分の殻に引きこもる (Ch19) |
| 天文学的な数 (of countable objects) | idiom is real (天文学的な数字/金額) but collocates with *abstract figures*, not floating objects | 無数の / 膨大な数の (Ch19) |
| 解く に (verb + bare に) | missing nominalizer | 解く**のに** (Ch19/20 — recurs; verb + のに) |
| 今には力がある | 今 can't take には as possessor | 今の私には力がある (Ch20) |
| 態度が…腹が立つ | double-が (が already claimed by 腹) | 態度**に**…腹が立つ (Ch21) |
| わざわざ ように | わざわざ is an adverb, can't take ように | わざわざ…催された (Ch21) |
| 恩を借りる | collides 恩を受ける + 借りができる | 借りができた / 恩に着る (Ch21) |

**Note:** the last six are grammar/collocation bugs the flag-only `lint_chapter` (§7) does NOT catch — missing nominalizers, particle-level collocation, double-が. These are exactly the class §2.7 warns about: **only a prose read finds them.** The lint is clean; the read is not. Confirms the lint must never satisfy a "verify" request.

**Tool requirement:** validate every N-gram of the generated draft against a real dictionary API (コトバンク / Weblio / JMdict). Anything not attested → flag. This is a **deterministic check the model must not be trusted to perform on itself**, because the model's confidence in a hallucinated compound is indistinguishable from its confidence in a real one.

**Corollary:** collocation errors (`遥かに違う` ✗, `期待を寄せる` ✗ for food) will NOT be caught by a word-existence check — both words exist. These need a collocation corpus, or they stay in the human's lane.

---

## 4. Workflow Shape

The loop that actually worked:

```
1. Author sends ONE chapter as its own docx + flags references/jokes inline
2. Model researches any unfamiliar reference (MUST search, not recall)
3. Author confirms reference rendering + any judgment calls UP FRONT
4. Model drafts full chapter
5. Author edits in their own master docx (author retains all editorial control)
6. Author re-uploads
7. Model runs the SEVEN-CLASS CHECK on the FULL PROSE (not just a scan):
   grammar · semantics · collocation · register · word-existence · consistency · naturalness
8. Author accepts / pushes back / explains intent
9. Repeat 5–8 until locked
10. Model appends new findings to this file (batched, every 3–4 chapters)
```

**Per-chapter upload beats whole-document upload for drafting.** Established Ch19. Parsing a growing master docx to find the one untranslated chapter is wasted work; a single-chapter docx is unambiguous. The master document is still needed for *cross-chapter consistency sweeps* (§6.2) — but that is a different operation, run at milestones, not every turn.

**The seven classes are load-bearing as an enumerated list.** "Check the chapter" produces a scan. "Check these seven named classes, on the prose" produces a read. Naming the classes is what forces coverage — see §2.7.

**Where a tool saves the most time:**
- **Step 7's consistency sweep** — fully automatable, currently the bulk of the token cost.
- **Step 2's reference lookup** — automatable search-before-render.
- **Step 4's draft** — the lint rules (§3.1–3.2) should run *before* the draft is shown to the author, so they never see 達-errors at all.

**Where a tool must NOT decide alone:**
- Any register/voice question (§2.3).
- Any wordplay adaptation (§2.4).
- Anything the author has tagged JA-authoritative.
- Cultural-reference calibration (§2.5) — flag, present options, let the human choose.

**Critical:** the author caught model errors repeatedly. The tool's job is to make the author's review *cheaper*, never to replace it.

---

## 5. Docx-Specific Gotchas

1. **`pandoc -t plain` drops ruby.** Use `unzip` + parse `word/document.xml`, looking for `<w:ruby>`, `<w:rubyBase>`, `<w:rt>`.
2. **`pandoc -t html` preserves italics as `<em>`** — this is the reliable way to extract thought-markers.
3. **A stale upload will silently show old content.** Verify against the file on disk, and if the author insists an edit exists, re-request the file rather than arguing.
4. **Copy-pasting from Word to a plain-text target destroys ruby entirely** (or mashes it inline with no delimiter). The furigana manifest is the mitigation.
5. **Search strings must match the author's actual headings** — the author may title a chapter slightly differently than agreed (e.g. 世界に vs 世に). Don't assume; locate the heading first.
6. Encoding: non-UTF8 bytes in extraction can break naive shell pipelines. Prefer Python with explicit encoding over shell grep for Japanese text.

---

## 6. Context & Token Economics (architectural constraint)

*Observed during real use. This is a first-class design constraint, not an optimization detail.*

### 6.1 The core problem: context accumulates, cost compounds

In a long chat session, **every new turn re-processes the entire conversation history.** The cost of a turn is therefore a function of how long the session has already run, not of how much work that turn actually does.

**Measured:** by hour ~5 of a working session, a *single* message consumed **~30% of the remaining usage window** — despite doing no more work than an equivalent message in hour 1. The expense came from context accumulation, not from the task.

**Practical consequence:** productivity per token degrades badly across a long session. The same chapter costs several times more to verify at the end of a session than at the start.

### 6.2 What this means for tool design

The instinctive fix — "read less of the manuscript" — is **wrong**, and we explicitly rejected it. Full-document reads were *cheap* relative to context bloat, and they caught real cross-chapter drift that a chapter-scoped check would have missed:
- Trevor's 丁寧語 creeping in only during Ch7–10 (visible only when comparing across chapters)
- The いや/いいえ character-voice split (required a whole-document sweep)
- Damien's お前 → ルミ arc (a cross-chapter register change)

**So: don't scope down the document. Scope down the CONVERSATION.**

### 6.3 Design implications

1. **Stateless-per-chapter operation.** Each chapter's work should be a fresh, self-contained call carrying only: (a) the chapter text, (b) the structured glossary/register bible, (c) the lessons file. NOT the accumulated chat transcript of the previous 14 chapters.

2. **Externalize state that currently lives in conversation.** Everything in §1 (glossary, register bible, orthography rules) and §2.4 (JA-authoritative line tags) is currently re-established through dialogue and re-read on every turn. As structured data loaded on demand, it costs a fraction of that.

3. **Deterministic checks must run OUTSIDE the model.** §2.1 (達 lint), §3.1–3.2, bracket punctuation, ruby manifest — these consume model turns today for zero reason. Every one of them is a regex. Moving them out removes both the token cost *and* the model's tendency to regress on them.

4. **Two verification modes, not one:**
   - **Cheap (default):** chapter-scoped diff against the previous version.
   - **Full sweep (on demand):** whole-document cross-chapter consistency. Run at milestones (e.g. every 5 chapters, and before publication), not every turn.

5. **Session boundaries are a real cost cliff.** After a usage-limit reset, resuming means re-establishing context. A tool should make resumption *cheap* by persisting state to disk rather than requiring the human to re-explain or re-upload.

### 6.4 Where the tokens SHOULD go

The turns worth paying for are the §2 judgment calls: register questions, wordplay adaptation, cultural calibration, and catching subtle semantic bugs (a dropped object flipping who healed whom; a subject-switch creating referential ambiguity). Everything else is friction that should be automated away so the budget is available for actual editorial judgment.

---

## 7. MCP Server — Built & Evolved (Ch19–21 sessions)

The spec in §6 was implemented. The server (`novel-translation-mcp`) now exists and was extended mid-project. What shipped, mapped to the requirements that motivated it:

**Tools exposed:** `list_projects`, `list_chapters`, `get_chapter`, `search_manuscript`, `get_glossary`, `propose_glossary_term`, `register_project`, `save_translation`, plus the two added mid-project below.

- **`get_context(chapter_n)`** — composite call returning {EN source, previous chapter's JA, glossary, staged terms} in one round-trip. Replaces the 4-call chapter startup (`list_chapters`→`get_glossary`→`get_chapter en`→`get_chapter n-1 ja`). Directly implements §6.3's "stateless-per-chapter, load state on demand." **Also makes the previous-chapter continuity read automatic** rather than something the model must remember (this is how the 境界結界 Ch18-continuity term was caught).
- **`lint_chapter(text)`** — runs the deterministic checks server-side (§3.1): 達/何故/貴方 orthography, bracket balance, non-word watchlist, Latin-char leakage, pronoun density. **Flag-only, and explicitly NON-substitutive for reading** — its own docstring encodes §2.7. This converts "I ran the scan" from a *claim* into a *verifiable fact*, which is the §2.7 mitigation.
- **`search_manuscript(query, lang)`** — grep-across-all-chapters returning only hits. This IS the §6.2 design: survey the whole manuscript, return ~1-2k chars, never load 50k words into context. **Clarification for future sessions:** "grep the manuscript" via this tool ≠ shelling out to bash; it's the intended selective-retrieval path and is cheap. Do not confuse it with reading the whole document.
- **Multi-manuscript `register_project`** — now takes a language→path map (`{"en": ..., "ja": ...}`), so the JA *master docx* is the canonical JA source, read directly. Retires the `translations/ja/*.txt` fallback. **Fixes a real correctness bug:** before this, the model read exported text files for JA, which could silently drift from the author's master.
- **JA `save_translation` guard** — refuses to write JA when a master docx is registered. The author's docx is the only writable JA artifact; the model can read (`get_chapter ja`) but not overwrite. Structurally prevents the model parking unreviewed drafts in the canonical slot (see §2.11).

**Observed server issues (for the maintainer):**
1. **Schema-migration crash.** After the multi-manuscript rebuild, `list_projects`/`get_chapter` threw a bare `KeyError: 'manuscript'` on a project registered under the OLD single-`manuscript_path` schema. Needs a migration/back-compat path for old records, and a human-readable error ("re-register with `manuscripts: {...}`") instead of a raw KeyError.
2. **`get_chapter` timed out (4 min, no result) where `get_context` succeeded** on the same chapter/lang moments later. Different code paths; the plain `get_chapter` is the one that stalled. Flag for debugging.
3. **New tools require a new session.** Tool definitions load at session start; adding a tool mid-conversation is invisible until the session restarts (though in one case a mid-session tool_search picked up the rebuilt server — behavior was inconsistent, so restart to be safe).
4. **`lint_chapter` false positive:** 到着し**たち**ょうど (past-tense た + ちょ-initial adverb ちょうど) fires the 達/たち rule. Fired 3× across Ch19–20. Candidate exemption: exempt たちょ/たちょう the way かたち/たちどころに are already exempted. Flag-only tools erring toward over-flagging is defensible, but this specific pattern is pure noise.
5. **Ruby loss persists through the server.** The stored/served JA still loses 誓約(ゲアス) ruby (plain-text layer). Consistent with §3.1 #3 and the furigana manifest being the mitigation — the manifest, not the served text, is the source of truth for ruby.

**Net:** the server now offloads every deterministic check and externalizes glossary/context state, which is exactly the §6.4 goal — free the token budget for §2 judgment calls. The Ch19–21 sessions spent their expensive turns on register (§2.10), the 前世/前回 distinction (§1.6), and reference verification (無敵の無気力カップル, the モブせか title), not on 達-hunting.

---

## Appendix: Running Furigana Manifest

| Ch | Ruby pairs |
|---|---|
| 1 | 誓約→ゲアス, 文字→ルーン |
| 2 | — |
| 3 | — |
| 4 | 誓約→ゲアス, 尸魂界→ソウル・ソサエティ, 禍進譚→かしんたん |
| 5 | — |
| 6 | (天魔教団→てんまきょうだん, optional) |
| 7 | 誓約→ゲアス |
| 8 | — |
| 9 | 強化魔法→バフ |
| 10 | 誓約→ゲアス |
| 11 | — |
| 12 | (千里眼→せんりがん, optional) |
| 13 | (龍鎖→りゅうさ, optional) |
| 14 | — |
| 15 | — |
| 16 | — |
| 17 | — |
| 18 | — (verified: no ruby terms appear in this chapter) |
| 19 | 誓約→ゲアス (誓約 and ルーン appear, but ルーン runs bare as a later instance; only 誓約 takes ruby) |
| 20 | — (境界結界, 天魔神教, 障壁 all run bare; no 誓約/ルーン) |
| 21 | — (no 誓約/ルーン/バフ; 境界結界, 天魔神教 run bare) |
