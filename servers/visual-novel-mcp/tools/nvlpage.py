# -*- coding: utf-8 -*-
"""The NVL page model: which entries share a screen, and how tall it is.

ONE model, used by two tools. paginate_nvl.py places page breaks with it;
verify_all.py checks the placed pages with it. They cannot disagree about
what a page is, which is the point -- and also the caveat: a fault in this
model is invisible to both. The measurement is made with the same font
Ren'Py renders, from the project's own gui.rpy numbers, so what can go wrong
is the PAGE WALK, and that is kept simple enough to read.

WHY PAGES ARE PLACED BY HEIGHT, NOT BY COUNT
--------------------------------------------
Ren'Py's NVL turns the page by a count of entries (gui.nvl_list_length).
A count is a proxy: four short replies leave a screen mostly empty, four
long paragraphs run off it. Measured over this project's 1,964 entries, a
cap of four turned the page 516 times at a median fill of 515 px out of
1,010 -- half-empty screens, and 40% more clicks than the same text packed
by height (308 screens). Fate/stay night paginates by lines for exactly this
reason. Ren'Py cannot, at runtime; but every scene here is GENERATED, so the
breaks can be placed at emit time, deterministically, and checked.

THE WALK
--------
Scene files are read in story order (script_diff.scene_order), because 14 of
43 files continue the previous file's page. Within a file:

  - a say line is an entry; `nvl clear` empties the page; a `call battle_*`
    empties it too (battle_loop clears the NVL window);
  - `if` / `elif` / `else` are followed the way the game follows them: each
    branch starts from the page as it was at the `if`, and after the block
    the TALLEST branch's page carries on. Summing branches as if they ran
    one after another put phantom breaks in the second branch;
  - a label with more than one way in cannot know which page it inherits,
    so its first entry starts a fresh page. There is one such label.

SOFTENING A BREAK
-----------------
An automatic break lands where the budget says, not on a beat. When the
next entry does not fit, the break is moved back by one or two entries if
that keeps a reply with the line it answers, or a paragraph of narration
with the line it sets up -- provided the page being closed stays at least
half full, and never across a branch boundary. The four-entry cap it
replaces broke arbitrarily 516 times; this breaks 300-odd times and
most of those on a paragraph of narration.
"""
import io
import os
import re

MARK = "# auto-page"
SAY = re.compile(r'^(\s*)(?:([a-z_0-9]+)\s+)?"(.*)"\s*$')
NOT_NVL = ("battle_say", "centered")
BRANCH = re.compile(r"^(\s*)(if\b|elif\b|else\s*:)")
LABEL = re.compile(r"^label\s+([A-Za-z_0-9]+)\s*:")
JUMP = re.compile(r"^\s*(?:jump|call)\s+([A-Za-z_0-9]+)\s*$")


def _gui_int(gui, name, default):
    m = re.search(r"^define gui\.%s\s*=\s*gui\.scale\((\d+)\)" % re.escape(name), gui, re.M) \
        or re.search(r"^define gui\.%s\s*=\s*(\d+)" % re.escape(name), gui, re.M)
    return int(m.group(1)) if m else default


class Metrics(object):
    """Font and layout numbers, read from the project's gui.rpy."""

    def __init__(self, project, sdk):
        from PIL import ImageFont
        gui = io.open(os.path.join(project, "game", "gui.rpy"), encoding="utf-8").read()
        self.size = _gui_int(gui, "nvl_text_size", 34)
        self.measure = _gui_int(gui, "nvl_measure", 1520)
        self.spacing = _gui_int(gui, "nvl_spacing", 20)
        self.text_ypos = _gui_int(gui, "nvl_text_ypos", 46)
        m = re.search(r"gui\.init\((\d+),\s*(\d+)\)", gui)
        self.screen_h = int(m.group(2)) if m else 1080
        quick = _gui_int(gui, "quick_button_text_size", 34)
        # the page's text must end above the quick menu (text + its borders),
        # and the page has its own bottom border
        self.limit = self.screen_h - (quick + 16) - 20
        self.font = ImageFont.truetype(
            os.path.join(sdk, "renpy", "common", "DejaVuSans.ttf"), self.size)
        self.line = sum(self.font.getmetrics())
        self._wrap = {}

    def lines(self, text):
        if text in self._wrap:
            return self._wrap[text]
        n, cur = 0, ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if self.font.getlength(t) <= self.measure or not cur:
                cur = t
            else:
                n += 1
                cur = w
        self._wrap[text] = n + (1 if cur else 0)
        return self._wrap[text]

    def entry(self, who, text):
        return (self.text_ypos if who else 0) + self.lines(text) * self.line

    def page(self, entries):
        if not entries:
            return 0
        return 30 + sum(e.height for e in entries) + self.spacing * (len(entries) - 1)


class Entry(object):
    __slots__ = ("who", "text", "file", "line", "indent", "frame", "height")

    def __init__(self, who, text, file, line, indent, frame, height):
        self.who, self.text, self.file, self.line = who, text, file, line
        self.indent, self.frame, self.height = indent, frame, height


def converging_labels(files):
    """Labels reached by more than one jump or call."""
    counts = {}
    for f in files:
        for ln in io.open(f, encoding="utf-8"):
            m = JUMP.match(ln)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return set(k for k, v in counts.items() if v > 1)


def _soften(pending, e, metrics, frame):
    """How many trailing entries to carry onto the new page with `e`.

    0 breaks right before `e`. 1 or 2 move the break back so a reply stays
    with its question, or narration with the line it introduces. Only
    entries from the same branch frame move, and only if the page being
    closed keeps at least half the budget.
    """
    if not e.who:
        return 0                                  # narration opens a page well
    best = 0
    for k in (1, 2):
        if len(pending) <= k:
            break
        moved = pending[-k:]
        if any(p.frame is not frame for p in moved):
            break
        head = pending[:-k]
        if metrics.page(head) < 0.5 * metrics.limit:
            break
        if metrics.page(moved + [e]) > metrics.limit:
            break
        prev = moved[0]
        if k == 1:
            # a reply after a question, or after the narration that set it up
            if prev.who and prev.text.rstrip().endswith(("?", "!")) or not prev.who:
                best = 1
            elif prev.who:
                best = 1                          # keep an exchange together
        elif k == 2:
            # narration, then a line, then this reply: keep all three
            if not moved[0].who and moved[1].who:
                best = 2
    return best


def walk(files, metrics, insert=True):
    """Page every file in order. Returns (insertions, tallest, breaks).

    insertions: [(file, line_index, indent)] -- where a break goes, when
    insert is True. tallest: (height, file, line, entries) for the tallest
    page seen. breaks: how many automatic breaks the walk decided on.
    """
    converge = converging_labels(files)
    pending = []
    insertions = []
    tallest = (0, None, 0, 0)
    breaks = 0
    root = object()
    force = False

    def record():
        nonlocal tallest
        h = metrics.page(pending)
        if h > tallest[0] and pending:
            tallest = (h, pending[-1].file, pending[-1].line, len(pending))

    for f in files:
        stack = []                                # [indent, start_page, ends, frame]
        frame = root
        lines = io.open(f, encoding="utf-8").read().split("\n")
        for i, raw in enumerate(lines):
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip())

            # close branch blocks the indentation has left
            while stack and indent <= stack[-1][0] and not (
                    indent == stack[-1][0] and BRANCH.match(raw) and not raw.lstrip().startswith("if")):
                top = stack.pop()
                top[2].append(pending)
                pending = max(top[2], key=metrics.page)
                frame = stack[-1][3] if stack else root

            m = BRANCH.match(raw)
            if m and raw.lstrip().startswith("if"):
                stack.append([indent, list(pending), [], object()])
                frame = stack[-1][3]
                continue
            if m and stack and indent == stack[-1][0]:      # elif / else
                stack[-1][2].append(pending)
                pending = list(stack[-1][1])
                stack[-1][3] = object()
                frame = stack[-1][3]
                continue

            lm = LABEL.match(raw)
            if lm:
                if lm.group(1) in converge:
                    force = True
                continue
            if s == "nvl clear" or s.startswith("nvl clear "):
                record()
                pending = []
                force = False
                continue
            if re.match(r"^call battle_", s):
                record()
                pending = []
                force = False
                continue

            sm = SAY.match(raw)
            if not sm or sm.group(2) in NOT_NVL or sm.group(3).startswith("audio/"):
                continue
            text = re.sub(r"\{/?[a-z]+\}", "", sm.group(3))
            e = Entry(sm.group(2), text, f, i, sm.group(1), frame, metrics.entry(sm.group(2), text))

            if insert and (force or metrics.page(pending + [e]) > metrics.limit):
                k = 0 if force else _soften(pending, e, metrics, frame)
                target = e if k == 0 else pending[-k]
                insertions.append((target.file, target.line, target.indent))
                breaks += 1
                record() if k == 0 else None
                if k:
                    head = pending[:-k]
                    tail = pending[-k:]
                    pending = head
                    record()
                    pending = tail
                else:
                    pending = []
                force = False
            pending.append(e)
            record()
        # a file's end closes whatever branches are open
        while stack:
            top = stack.pop()
            top[2].append(pending)
            pending = max(top[2], key=metrics.page)
    return insertions, tallest, breaks
