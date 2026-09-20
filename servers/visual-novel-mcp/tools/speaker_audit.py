# -*- coding: utf-8 -*-
"""Find dialogue that was emitted as narration with its label still in it.

    python speaker_audit.py <project-dir> [patterns.json]

WHAT THIS CATCHES
-----------------
An emitter maps document speaker labels to Ren'Py character variables. A
label with no entry in that map is not an error: the line is emitted as
NARRATION, with the label still inside the string --

    "Some Name: <opening quote>...<closing quote>"

-- and in play it reads as the narrator saying the character's name aloud.
It happens every time a new character starts speaking inside a scene whose
emitter predates them, which is to say every time the author writes one in.

⚠ WHY NO EXISTING CHECK SEES IT, and why this file is separate from all of
them. The failure is invisible to each one for a DIFFERENT reason, so no
amount of strengthening any of them would have found it:

  script_diff   compares the document's text against the emitted text and
                finds them identical -- because they ARE identical. It
                compares WHAT IS SAID, never WHO SAYS IT.
  sprite_audit  looks for speakers with no sprite. The label was never
                recognized as a speaker at all, so there is no speaker to
                be missing a sprite.
  a tail cap    is the one thing that can notice a scene has grown past
                itself, and only if it is set near the scene's real length.
                Set near a ceiling it protects nothing.

This check reads the EMITTED SCENE, which is the only place the fault is
visible, and it decides using `speaker` from patterns.json -- the author's
own document convention, which no emitter has a copy of. That independence
is the point: a checker that shared the emitters' speaker maps would agree
with them and find nothing, which is how this class of fault survives.

The same lesson is recorded in patterns.json's own `_comment`, about stat
block lines emitted as spoken narration: "script_diff CANNOT catch this ...
Only reading the emitted scene finds it."

WHAT KEEPS IT QUIET
-------------------
`speaker` alone is loose -- it matches any capitalized run before a colon,
so ordinary narration ("Then it hit me: ...") matches it too. A line is only
reported when the text AFTER the label opens a quotation. A narrator does not
introduce a quotation with a bare name and a colon; an unmapped speaker
always does, because that is verbatim how the document writes dialogue.
"""
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import script_diff  # noqa: E402

# A narration line is a single quoted string alone on its line. A spoken line
# has a character variable in front of it and a menu choice has a colon after
# it; neither shape matches here.
NARRATION = re.compile(r'^\s*"(.*)"\s*$')

# The opening of a quotation, in any of the forms a document uses.
OPENS_QUOTE = re.compile(r'^[“‘"\']')


def findings(project, patterns=None):
    if patterns is None:
        patterns = os.path.join(project, "game", "patterns.json")
    speaker = script_diff.load_patterns(patterns)[0]

    out = []
    scenes = os.path.join(project, "game", "scenes")
    for path in sorted(glob.glob(os.path.join(scenes, "*.rpy"))):
        for n, line in enumerate(io.open(path, encoding="utf-8"), 1):
            m = NARRATION.match(line.rstrip("\n"))
            if not m:
                continue
            text = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            hit = speaker.match(text)
            if not hit:
                continue
            if not OPENS_QUOTE.match(text[hit.end():]):
                continue
            out.append((os.path.basename(path), n, text[:hit.end()].strip()))
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    project = sys.argv[1]
    patterns = sys.argv[2] if len(sys.argv) > 2 else None

    bad = findings(project, patterns)
    if not bad:
        return 0

    print("DIALOGUE EMITTED AS NARRATION (%d):" % len(bad))
    for name, n, label in bad:
        print("  %s:%d  %s" % (name, n, label))
    print("")
    print("Each line above is a document speaker label that reached the game")
    print("inside a narration string. The emitter covering that scene has no")
    print("entry for it: add the label to that file's SPEAKERS map, or -- if")
    print("the scene has grown an end -- give the scene an anchor and start a")
    print("new emitter from it, with the label mapped there.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
