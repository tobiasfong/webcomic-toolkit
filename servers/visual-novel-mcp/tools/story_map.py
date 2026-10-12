# -*- coding: utf-8 -*-
"""Draw a living story map for a Ren'Py visual novel: choices, affection
ranges, fights, and the numbers behind them.

    python story_map.py <project-dir> [--out story_map.html]

The project is the folder that holds `game/`. The page is written beside it
(or to --out) and is meant to be REDRAWN on every change, from the scripts
themselves -- nothing in it is typed by hand, so it cannot drift from the
game. Re-run it after you edit a scene; add it to whatever builds your game.

WHAT IT SHOWS
-------------
1. **Affection over the story.** For every meter (a number the story adds to
   and subtracts from -- affection, trust, corruption), a band from its
   lowest to its highest possible value after each choice, as the player
   could have played it. Hover for exact ranges.
2. **The timeline.** Every scene in story order, every `menu:` choice with
   its options, and what each option does: meter changes, flags it sets,
   fights it leads to, where it jumps.
3. **Combat** (optional). Every fight in the order the story reaches it,
   with whatever numbers your game wants to show -- enemy HP, moves,
   damage -- plus extra tables and a CALCULATOR: pick the player's gear or
   skills from dropdowns and see the finished numbers.

HOW IT READS THE STORY (no setup needed for parts 1 and 2)
----------------------------------------------------------
Labels, jumps, calls and fall-throughs come from the server's own parser
(graph.Analysis). Story order is a walk from `label start`. A `menu:` choice
whose block jumps to a label that only that choice reaches takes that
label's changes with it (they are the option's, not everyone's); the walk
rejoins the main line where branches converge. Meters are found
automatically: any `default` whose name ends in `_affection`, or every
variable named in the config.

Ranges assume each choice is independent of the last -- exact for most VNs;
if a later option is gated on an earlier meter value, the band can claim a
value no player can reach. Choices built from custom screens (not `menu:`)
are not seen; say so in the config's "notes" and they are printed on the
page, so the gap is visible rather than silent.

CONFIG (optional): <project>/story_map.json
-------------------------------------------
    {
      "title": "My Visual Novel",
      "meters": {"ayla_affection": "Ayla", "mira_affection": "Mira"},
      "meter_max": 100,
      "acts": [["prologue_", "Prologue"], ["ch1_", "Chapter 1"]],
      "fight_prefix": "battle_",
      "hp_variable": "player_max_hp",
      "combat": "story_map_combat.py",
      "notes": ["Anything the map cannot see, said on the page."]
    }

Every key is optional. "acts" groups labels by name prefix. "fight_prefix"
marks `call` targets that are fights. "hp_variable" is shown beside each
fight as it stood when the story got there.

COMBAT DATA: <project>/<combat> -- a Python file with one function
-----------------------------------------------------------------
    def combat_data(project_dir):
        return {
          "fights": {                         # keyed by the label the story calls
            "battle_wolves": {
              "title": "Wolves at the ford",
              "enemies": [{"name": "Wolf", "count": 2, "hp": 20,
                           "moves": [{"name": "Bite", "pp": 20,
                                      "damage": "8", "effect": ""}]}],
              "notes": ["music: tense.ogg"]}},
          "tables": [{"title": "Player commands",
                      "columns": ["Command", "PP", "Effect"],
                      "rows": [["Slash", 20, "10 damage"]]}],
          "calculator": {
            "title": "Your kit, finished",
            "axes": [{"id": "weapon", "label": "Weapon",
                      "options": [["", "none"], ["iron", "Iron sword"]]}],
            "columns": ["Command", "PP", "Damage", "Effect"],
            "results": {"iron": {"rows": [["Slash", 20, "15", ""]],
                                 "notes": ["+5 damage from the sword"]}}}}

Return plain lists, numbers and strings only. The tool does no arithmetic of
its own on purpose: compute the numbers WITH YOUR GAME'S OWN CODE (import
your combat module, or load it the way your test harness does) so the page
and the game can never disagree. A calculator result is keyed by the axis
values in axis order, joined by "|". See examples/story_map_demo/.

Never blocks a build: a map that cannot be drawn prints a warning and exits 0.
"""
import html
import importlib.util
import io
import json
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import graph  # noqa: E402

RE_LABEL = re.compile(r"^(\s*)label\s+([A-Za-z_.][\w.]*)\s*(?:\([^)]*\))?\s*:")
RE_MENU = re.compile(r"^(\s*)menu(?:\s+[\w.]+)?\s*:")
RE_CHOICE = re.compile(r'^(\s*)"((?:[^"\\]|\\.)*)"\s*(?:if\s+(.+?))?\s*:\s*$')
RE_JUMP = re.compile(r"^\s*jump\s+([\w.]+)\s*$")
RE_CALL = re.compile(r"^\s*call\s+(?!screen\b)([\w.]+)")
RE_FLAG = re.compile(r"^\s*\$?\s*([A-Za-z_]\w*)\s*=\s*(True|False)\s*$")
RE_DEFAULT_AFF = re.compile(r"^default\s+(\w+_affection)\s*=", re.M)


# ------------------------------------------------------------------ config
def load_config(project):
    p = os.path.join(project, "story_map.json")
    cfg = json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else {}
    cfg.setdefault("title", os.path.basename(os.path.abspath(project)))
    cfg.setdefault("meter_max", 100)
    cfg.setdefault("acts", [])
    cfg.setdefault("fight_prefix", "battle_")
    cfg.setdefault("notes", [])
    return cfg


def find_meters(game_dir, cfg):
    if cfg.get("meters"):
        return dict(cfg["meters"])
    found = {}
    for root, _d, files in os.walk(game_dir):
        for f in files:
            if f.endswith(".rpy"):
                src = io.open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                for v in RE_DEFAULT_AFF.findall(src):
                    found[v] = v[: -len("_affection")].replace("_", " ").title()
    return dict(sorted(found.items()))


# ------------------------------------------------------------------ reading
def label_bodies(game_dir, an):
    """{label: [(indent, code), ...]} -- each label's own lines."""
    bodies = {}
    by_file = {}
    for name, where in an.labels.items():
        by_file.setdefault(where["file"], []).append((where["line"], name))
    for rel, labs in by_file.items():
        lines = io.open(os.path.join(game_dir, rel), encoding="utf-8", errors="replace").read().split("\n")
        labs.sort()
        for k, (line, name) in enumerate(labs):
            start = line  # 1-based label line; body is after it
            end = labs[k + 1][0] - 1 if k + 1 < len(labs) else len(lines)
            body = []
            for raw in lines[start:end]:
                code = raw.split("#", 1)[0] if not raw.lstrip().startswith('"') else raw
                if not code.strip():
                    continue
                if re.match(r"^\S", raw) and not RE_LABEL.match(raw):
                    break           # a top-level statement ends the label
                body.append((len(raw) - len(raw.lstrip()), code.rstrip()))
            bodies[name] = body
    return bodies


def effects_of(lines, cfg, meters):
    """(deltas {meter: n}, effects [(kind, text)], jump target or None)."""
    deltas, effects, jump = {}, [], None
    hp_re = re.compile(r"^\s*\$?\s*%s\s*=\s*(\d+)" % re.escape(cfg["hp_variable"])) if cfg.get("hp_variable") else None
    for _ind, code in lines:
        for var in meters:
            for m in re.finditer(r"\b%s\s*(\+=|-=)\s*(\d+)" % re.escape(var), code):
                n = int(m.group(2)) * (1 if m.group(1) == "+=" else -1)
                deltas[var] = deltas.get(var, 0) + n
        m = RE_FLAG.match(code)
        if m and m.group(1) not in meters:
            effects.append(("flag", "%s = %s" % (m.group(1), m.group(2))))
        if hp_re:
            m = hp_re.match(code)
            if m:
                effects.append(("hp", "max HP %s" % m.group(1)))
        m = RE_CALL.match(code)
        if m and m.group(1).startswith(cfg["fight_prefix"]):
            effects.append(("fight", "fight: " + m.group(1)))
        m = RE_JUMP.match(code)
        if m and jump is None:
            jump = m.group(1)
    return deltas, effects, jump


def split_label(body):
    """The label's lines as [("lines", [...]) | ("menu", [(text, cond, block)])]."""
    out, cur, i = [], [], 0
    while i < len(body):
        ind, code = body[i]
        if RE_MENU.match(code):
            if cur:
                out.append(("lines", cur))
                cur = []
            menu_ind, opts = ind, []
            i += 1
            while i < len(body) and body[i][0] > menu_ind:
                m = RE_CHOICE.match(body[i][1])
                if m and body[i][0] > menu_ind:
                    c_ind, block = body[i][0], []
                    i += 1
                    while i < len(body) and body[i][0] > c_ind:
                        block.append(body[i])
                        i += 1
                    opts.append((m.group(2), m.group(3), block))
                else:
                    i += 1              # a menu caption line
            out.append(("menu", opts))
            continue
        cur.append((ind, code))
        i += 1
    if cur:
        out.append(("lines", cur))
    return out


def read_story(project, cfg, meters):
    game = os.path.join(project, "game")
    an = graph.Analysis(game)
    bodies = label_bodies(game, an)
    def menu_closes(src):
        """True when the label ENDS in a menu whose every option jumps or
        returns. The parser still records a fall-through from such a label
        (it sees "last statement: menu"), which would make a branch-only
        label look reachable twice and hand its changes to every player."""
        parts = split_label(bodies.get(src, []))
        if not parts or parts[-1][0] != "menu":
            return False
        return all(any(RE_JUMP.match(c) or c.strip() == "return" for _i, c in block)
                   for _t, _c, block in parts[-1][1])

    succ = {}
    indeg = {}
    for src, es in an.edges.items():
        for e in es:
            t = e.get("target")
            if not t or t not in an.labels or t.startswith(cfg["fight_prefix"]):
                continue
            if e.get("kind") == "fallthrough" and menu_closes(src):
                continue
            succ.setdefault(src, []).append(t)
            indeg[t] = indeg.get(t, 0) + 1

    def branch_chain(start):
        """Labels that belong to ONE option: from its jump target, onward
        while each next label is reached from nowhere else."""
        chain, cur = [], start
        while cur and cur in an.labels and indeg.get(cur, 0) == 1 and cur not in chain:
            chain.append(cur)
            nxt = succ.get(cur, [])
            cur = nxt[0] if len(nxt) == 1 else None
        return chain

    items, seen, problems = [], set(), []
    # A game that builds choices from its own screens is invisible to a
    # `menu:` reader, and the changes inside those branches would be counted
    # as if every player got them. Say so on the page instead of drawing a
    # confident wrong band.
    screened = sorted({lab for lab, body in bodies.items()
                       if any(re.search(r"\bcall\s+screen\b|renpy\.call_screen\(", c) for _i, c in body)})
    if screened:
        problems.append("%d label(s) show a screen with `call screen` (e.g. %s). If any of those are "
                        "CHOICES, the map cannot see them: changes inside their branches are counted "
                        "for every player, so the bands are too wide. Choices written as `menu:` are "
                        "read exactly." % (len(screened), ", ".join(screened[:3])))
    owned = set()
    stack = ["start"] if "start" in an.labels else []
    if not stack:
        problems.append("no `label start` -- nothing to walk")
    while stack:
        lab = stack.pop()
        if lab in seen or lab in owned:
            continue
        seen.add(lab)
        for kind, part in split_label(bodies.get(lab, [])):
            if kind == "lines":
                d, e, _j = effects_of(part, cfg, meters)
                if d or e:
                    items.append({"kind": "scene", "label": lab, "deltas": d, "effects": e})
                continue
            options = []
            for text, cond, block in part:
                d, e, j = effects_of(block, cfg, meters)
                chain = branch_chain(j) if j else []
                for c in chain:
                    owned.add(c)
                    for k2, p2 in split_label(bodies.get(c, [])):
                        if k2 == "lines":
                            d2, e2, _ = effects_of(p2, cfg, meters)
                            for v, n in d2.items():
                                d[v] = d.get(v, 0) + n
                            e += e2
                        else:
                            problems.append("%s: a menu inside a branch of %s is not followed" % (c, lab))
                options.append({"text": text, "cond": cond, "deltas": d, "effects": e,
                                "jump": j, "branch": chain})
                # the walk continues past the branch, at its convergence point
                tail = chain[-1] if chain else j
                for t in succ.get(tail, []) if tail else []:
                    if t not in seen:
                        stack.append(t)
            items.append({"kind": "choice", "label": lab, "options": options})
        for t in reversed(succ.get(lab, [])):
            if t not in seen and t not in owned:
                stack.append(t)
    return items, problems


def ranges(items, meters):
    lo = {m: 0 for m in meters}
    hi = {m: 0 for m in meters}
    pts = [("Start", {m: (0, 0) for m in meters})]
    for it in items:
        if it["kind"] == "scene":
            if not it["deltas"]:
                continue
            for v, n in it["deltas"].items():
                lo[v] += n
                hi[v] += n
        else:
            outs = [o["deltas"] for o in it["options"]] or [{}]
            if not any(outs):
                continue
            for v in meters:
                vals = [o.get(v, 0) for o in outs]
                lo[v] += min(vals)
                hi[v] += max(vals)
        pts.append((it["label"], {m: (lo[m], hi[m]) for m in meters}))
    return pts


# ------------------------------------------------------------------ combat
def load_combat(project, cfg):
    if not cfg.get("combat"):
        return None
    path = os.path.join(project, cfg["combat"])
    spec = importlib.util.spec_from_file_location("story_map_combat", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path))
    spec.loader.exec_module(mod)
    return mod.combat_data(project)


def start_value(project, var):
    """The value a `default` gives a variable, for the HP shown at the first fight."""
    if not var:
        return None
    rx = re.compile(r"^default\s+%s\s*=\s*(\d+)" % re.escape(var), re.M)
    for root, _d, files in os.walk(os.path.join(project, "game")):
        for f in files:
            if f.endswith(".rpy"):
                m = rx.search(io.open(os.path.join(root, f), encoding="utf-8", errors="replace").read())
                if m:
                    return m.group(1)
    return None


def fights_in_order(items, cfg, hp=None):
    out = []
    for it in items:
        groups = [(it["label"], it["effects"])] if it["kind"] == "scene" else \
                 [("%s, if \u201c%s\u201d" % (it["label"], o["text"][:40]), o["effects"]) for o in it["options"]]
        for where, effects in groups:
            for kind, text in effects:
                if kind == "hp":
                    hp = text.split()[-1]
                elif kind == "fight":
                    out.append((text[len("fight: "):], where, hp))
    return out


def table_html(title, columns, rows, e):
    p = ["<h3>%s</h3><table><tr>%s</tr>" % (e(title), "".join("<th>%s</th>" % e(str(c)) for c in columns))]
    for r in rows:
        p.append("<tr>%s</tr>" % "".join(
            '<td%s>%s</td>' % (' class="n"' if isinstance(c, (int, float)) else "", e(str(c))) for c in r))
    p.append("</table>")
    return "".join(p)


def combat_html(data, items, cfg):
    e = html.escape
    p = ['<h2 id="combat">Combat</h2>']
    fights = data.get("fights", {})
    placed = set()
    if fights:
        p.append("<h3>Fights, in story order</h3>")
    for key, where, hp in fights_in_order(items, cfg, cfg.get("_hp_start")):
        f = fights.get(key)
        if f is None:
            p.append('<div class="card"><b>%s</b> \u2014 called by the story, missing from the combat data</div>' % e(key))
            continue
        if key in placed:
            continue
        placed.add(key)
        meta = [e(where)] + (["max HP <b>%s</b>" % e(str(hp))] if hp else []) + [e(n) for n in f.get("notes", [])]
        p.append('<div class="card fight"><b>%s</b> <span class="meta">\u00b7 %s</span>'
                 % (e(f.get("title", key)), " \u00b7 ".join(meta)))
        p.append("<table><tr><th>Enemy</th><th>HP</th><th>Move</th><th>PP</th><th>Damage</th><th>Effect</th></tr>")
        for en in f.get("enemies", []):
            name = en["name"] + (" \u00d7%d" % en["count"] if en.get("count", 1) > 1 else "")
            for k, mv in enumerate(en.get("moves", []) or [{}]):
                p.append('<tr><td>%s</td><td class="n">%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                         % (e(name) if k == 0 else "", en.get("hp", "") if k == 0 else "",
                            e(str(mv.get("name", ""))), mv.get("pp", ""), e(str(mv.get("damage", ""))),
                            e(str(mv.get("effect", "")))))
        p.append("</table></div>")
    unplaced = [k for k in fights if k not in placed]
    if unplaced:
        p.append('<p class="meta">In the combat data but not called by any scene yet: %s</p>' % e(", ".join(unplaced)))
    for t in data.get("tables", []):
        p.append(table_html(t["title"], t["columns"], t["rows"], e))
    calc = data.get("calculator")
    if calc:
        p.append('<h3>%s</h3><div class="card" id="calc"><div class="axes">' % e(calc.get("title", "Calculator")))
        for ax in calc["axes"]:
            p.append('<label>%s <select data-axis="%s">%s</select></label>' % (
                e(ax["label"]), e(ax["id"]),
                "".join('<option value="%s">%s</option>' % (e(v), e(lbl)) for v, lbl in ax["options"])))
        p.append('</div><table><thead><tr>%s</tr></thead><tbody id="calc-rows"></tbody></table>'
                 '<p class="meta" id="calc-notes"></p></div>' % "".join("<th>%s</th>" % e(c) for c in calc["columns"]))
        p.append("""<script>
(function(){
const res=%s, sel=[...document.querySelectorAll('#calc select')];
const body=document.getElementById('calc-rows'), notes=document.getElementById('calc-notes');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function draw(){const k=res[sel.map(s=>s.value).join('|')];
  if(!k){body.innerHTML='<tr><td colspan="9">No result for this combination.</td></tr>';notes.textContent='';return;}
  body.innerHTML=k.rows.map(r=>'<tr>'+r.map(c=>'<td'+(typeof c==='number'?' class="n"':'')+'>'+esc(c)+'</td>').join('')+'</tr>').join('');
  notes.textContent=(k.notes||[]).join(' \\u00b7 ');}
sel.forEach(s=>s.addEventListener('change',draw));draw();})();
</script>""" % json.dumps(calc["results"], ensure_ascii=False))
    return "\n".join(p)


# ------------------------------------------------------------------ page
CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--panel:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--ink3:#8a8984;
--rule:#e4e3df;--spine:#c9c8c2;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#9b59d0;--s5:#c8a400;--chip:#f1f0ec;--warn:#b54708}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;--panel:#222220;
--ink:#ffffff;--ink2:#c3c2b7;--ink3:#8d8c84;--rule:#34332f;--spine:#4a4943;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#a875d8;--s5:#d4b21f;--chip:#2c2b28;--warn:#f79009}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px}h3{font-size:15px;margin:22px 0 8px;color:var(--ink2);text-transform:uppercase;letter-spacing:.06em}
.meta{color:var(--ink2);font-size:13px}.warn{color:var(--warn)}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px 16px}.card.fight{margin:10px 0}
svg{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--rule);stroke-width:1}.tick{fill:var(--ink3);font-size:11px}
.line{fill:none;stroke-width:2}.line.lo{stroke-dasharray:4 3;stroke-width:1.5}.band{stroke:none;opacity:.14}
.s1{stroke:var(--s1);fill:var(--s1)}.s2{stroke:var(--s2);fill:var(--s2)}.s3{stroke:var(--s3);fill:var(--s3)}.s4{stroke:var(--s4);fill:var(--s4)}.s5{stroke:var(--s5);fill:var(--s5)}
.line.s1,.line.s2,.line.s3,.line.s4,.line.s5{fill:none}.dlabel{fill:var(--ink);font-size:12px}.sw{stroke:none}
.xh{stroke:var(--ink3);stroke-width:1}.hit{fill:transparent;cursor:crosshair}
#tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:8px 10px;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;min-width:170px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600}td.n{font-variant-numeric:tabular-nums}
.flow{position:relative;margin-left:10px;padding-left:22px;border-left:2px solid var(--spine)}
.scene{margin:6px 0;font-size:13.5px;color:var(--ink2)}.choice{margin:12px 0}
.opt{margin:6px 0 6px 14px}.opt .t{font-weight:600}
.chip{display:inline-block;background:var(--chip);border-radius:6px;padding:1px 7px;margin:2px 4px 2px 0;font-size:12px}
.axes{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px}select{font:inherit}
"""


def chart_svg(pts, meters, vmax):
    names = list(meters)
    W, H, L, Rt, T, B = 760, 300, 44, 130, 16, 56
    pw, ph = W - L - Rt, H - T - B
    n = max(1, len(pts) - 1)
    lo_all = min([0] + [r[m][0] for _l, r in pts for m in names])
    hi_all = max([vmax] + [r[m][1] for _l, r in pts for m in names])
    # round ticks: the smallest of 1-2-5 x 10^k giving at most six of them
    span, step = max(1, hi_all - lo_all), 1
    for k in range(0, 7):
        for b in (1, 2, 5):
            if span / float(b * 10 ** k) <= 5:
                step = b * 10 ** k
                break
        else:
            continue
        break
    lo_all = (lo_all // step) * step
    hi_all = -((-hi_all) // step) * step
    X = lambda i: L + pw * i / n
    Y = lambda v: T + ph * (1 - (v - lo_all) / float(hi_all - lo_all or 1))
    g = []
    v = lo_all
    while v <= hi_all:
        g.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (L, L + pw, Y(v), Y(v)))
        g.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%d</text>' % (L - 8, Y(v) + 4, v))
        v += step
    for i, (lab, _r) in enumerate(pts):
        g.append('<text class="tick" x="%.1f" y="%d" text-anchor="end" transform="rotate(-35 %.1f %d)">%s</text>'
                 % (X(i), H - B + 16, X(i), H - B + 16, html.escape(lab)))
    ends = []
    for k, m in enumerate(names):
        hiP = " ".join("%.1f,%.1f" % (X(i), Y(r[m][1])) for i, (_l, r) in enumerate(pts))
        loP = " ".join("%.1f,%.1f" % (X(i), Y(r[m][0])) for i, (_l, r) in reversed(list(enumerate(pts))))
        s = (k % 5) + 1
        g.append('<polygon class="band s%d" points="%s %s"/>' % (s, hiP, loP))
        g.append('<polyline class="line s%d" points="%s"/>' % (s, hiP))
        g.append('<polyline class="line lo s%d" points="%s"/>' % (s, " ".join(
            "%.1f,%.1f" % (X(i), Y(r[m][0])) for i, (_l, r) in enumerate(pts))))
        last = pts[-1][1][m]
        ends.append([Y(last[1]), m, last, s])
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 15)
    for y, m, last, s in ends:
        g.append('<text class="dlabel" x="%d" y="%.1f"><tspan class="sw s%d">\u25a0</tspan> %s %s</text>'
                 % (L + pw + 8, y + 4, s, html.escape(meters[m]),
                    "%d" % last[1] if last[0] == last[1] else "%d\u2013%d" % (last[0], last[1])))
    g.append('<line id="xh" class="xh" x1="0" x2="0" y1="%d" y2="%d" visibility="hidden"/>' % (T, T + ph))
    g.append('<rect class="hit" x="%d" y="%d" width="%d" height="%d"/>' % (L, T, pw, ph))
    return ('<svg id="chart" viewBox="0 0 %d %d" role="img" aria-label="Range of each meter after each choice">%s</svg>'
            % (W, H, "".join(g)))


def chips(deltas, effects, meters):
    e = html.escape
    out = ['<span class="chip">%s %+d</span>' % (e(meters[v]), n) for v, n in sorted(deltas.items())]
    out += ['<span class="chip %s">%s</span>' % (k, e(t)) for k, t in effects]
    return "".join(out)


def act_of(label, cfg):
    for pre, name in sorted(cfg["acts"], key=lambda a: -len(a[0])):
        if label.startswith(pre):
            return name
    return None


def page(cfg, meters, items, pts, problems, combat):
    e = html.escape
    p = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
         "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
         "<title>%s \u2014 story map</title><style>%s</style></head><body><main>" % (e(cfg["title"]), CSS),
         "<h1>%s</h1>" % e(cfg["title"]),
         "<p class=\"meta\">Drawn from the game's own scripts by story_map.py. "
         "%d choices, %d meters.</p>" % (sum(1 for i in items if i["kind"] == "choice"), len(meters))]
    for note in list(cfg["notes"]) + problems:
        p.append('<p class="meta warn">\u26a0 %s</p>' % e(note))
    if meters:
        p.append("<h2>Affection</h2><div class=\"card\">%s</div>" % chart_svg(pts, meters, cfg["meter_max"]))
        p.append("<p class=\"meta\">Each band runs from the lowest to the highest value a player can "
                 "have after that point; the solid line is the highest, the dashed the lowest.</p>")
    p.append("<h2>Timeline</h2><div class=\"flow\">")
    act = object()
    for it in items:
        a = act_of(it["label"], cfg)
        if a != act and a is not None:
            p.append("<h3>%s</h3>" % e(a))
            act = a
        if it["kind"] == "scene":
            p.append('<div class="scene"><b>%s</b> %s</div>' % (e(it["label"]), chips(it["deltas"], it["effects"], meters)))
            continue
        p.append('<div class="card choice"><b>Choice in %s</b>' % e(it["label"]))
        for o in it["options"]:
            extra = []
            if o["cond"]:
                extra.append('<span class="chip">only if %s</span>' % e(o["cond"]))
            if o["branch"]:
                extra.append('<span class="chip">branch: %s</span>' % e(" \u2192 ".join(o["branch"])))
            elif o["jump"]:
                extra.append('<span class="chip">\u2192 %s</span>' % e(o["jump"]))
            p.append('<div class="opt"><div class="t">%s</div>%s%s</div>'
                     % (e(o["text"]), chips(o["deltas"], o["effects"], meters), "".join(extra)))
        p.append("</div>")
    p.append("</div>")
    if combat:
        p.append(combat_html(combat, items, cfg))
    if meters:
        data = json.dumps([{"at": lab, **{meters[m]: r[m] for m in meters}} for lab, r in pts])
        p.append("""<div id="tip"></div><script>
const pts=%s, names=%s;
const svg=document.getElementById('chart'), hit=svg.querySelector('.hit'), xh=document.getElementById('xh'), tip=document.getElementById('tip');
function at(ev){const r=svg.getBoundingClientRect(), vb=svg.viewBox.baseVal, x=(ev.clientX-r.left)*vb.width/r.width;
const L=+hit.getAttribute('x'), w=+hit.getAttribute('width'), n=Math.max(1,pts.length-1);return Math.max(0,Math.min(n,Math.round((x-L)/w*n)));}
hit.addEventListener('mousemove',ev=>{const i=at(ev),L=+hit.getAttribute('x'),w=+hit.getAttribute('width'),n=Math.max(1,pts.length-1),x=L+w*i/n;
xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.setAttribute('visibility','visible');const p=pts[i];
tip.innerHTML='<b>'+p.at+'</b>'+names.map((h,k)=>'<div><span style="color:var(--s'+(k%%5+1)+')">\\u25a0</span> '+h+': '+(p[h][0]==p[h][1]?p[h][0]:p[h][0]+'\\u2013'+p[h][1])+'</div>').join('');
tip.style.display='block';tip.style.left=Math.min(ev.clientX+14,innerWidth-200)+'px';tip.style.top=(ev.clientY+14)+'px';});
hit.addEventListener('mouseleave',()=>{tip.style.display='none';xh.setAttribute('visibility','hidden');});
</script>""" % (data, json.dumps(list(meters.values()))))
    p.append("</main></body></html>")
    return "\n".join(p)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    project = os.path.abspath(argv[0])
    out = os.path.join(project, "story_map.html")
    if "--out" in argv:
        out = os.path.abspath(argv[argv.index("--out") + 1])
    try:
        cfg = load_config(project)
        cfg["_hp_start"] = start_value(project, cfg.get("hp_variable"))
        meters = find_meters(os.path.join(project, "game"), cfg)
        items, problems = read_story(project, cfg, meters)
        pts = ranges(items, meters)
        combat = None
        try:
            combat = load_combat(project, cfg)
        except Exception:
            problems.append("the combat data could not be loaded: " + traceback.format_exc().strip().splitlines()[-1])
        io.open(out, "w", encoding="utf-8", newline="\n").write(page(cfg, meters, items, pts, problems, combat))
        print("story_map: wrote %s (%d choices, %d meters%s)" % (
            out, sum(1 for i in items if i["kind"] == "choice"), len(meters),
            ", %d warning(s) on the page" % len(problems) if problems else ""))
    except Exception:
        print("story_map: WARNING, the map could not be drawn:\n" + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
