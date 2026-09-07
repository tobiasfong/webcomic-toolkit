# -*- coding: utf-8 -*-
"""The author's numbers in the docx against the numbers the game actually uses.

    python spec_check.py <master.docx> <project-dir> [patterns.json]

WHY
---
The combat spec lives in fenced blocks that are deliberately NOT emitted --
they are a brief for the implementer, not player text. That is correct, and it
means nothing compares them to the engine. The two can drift apart in silence:
the author retypes a figure, an editor's stray undo restores an old one, or a
value is tuned in combat.rpy and the script is never updated. `script_diff`
cannot see any of it, because it only checks the prose that ships.

MOVES ARE KEYED BY THEIR OWNER, NOT BY NAME
-------------------------------------------
Move names are NOT unique, and the numbers behind one name are not constant.
ENEMIES SCALE as a story goes on: a boss and her underlings can throw the same
named weapon for 15 and for 5, and the same underlings can be worth 10 HP in an
early fight and 20 in a late one. Every one of those figures is correct.

Keyed globally on the move name, the first version of this tool called that a
mismatch -- a confident, wrong finding against code that was right. A checker
that cries wolf gets ignored, which is worse than not having one. So ownership
is tracked on both sides (the engine from each `Combatant(...)` call, the spec
from the `<Name>, <n> HP` line opening each roster entry), and each name holds
the SET of statlines the engine uses anywhere: a spec claim passes if it
matches one of them.

The cost of that is honest to state: this catches a figure that exists in the
script and NOWHERE in the engine, which is the drift it was built for. It would
not catch two encounters' values swapped with each other.

⚠ IT REPORTS WHAT IT COULD NOT READ. A checker that quietly skips the lines it
does not understand grades itself on the easy ones and prints a clean sheet.
The unparsed numeric spec lines are listed, and counted separately from
agreements, so the coverage is visible rather than assumed.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_diff  # noqa: E402

PLAYER = "<player>"


def norm(s):
    return " ".join(s.lower().replace("’", "'").split())


# ---------------------------------------------------------------- the engine

def _literal(src, name):
    """Evaluate a top-level table out of combat.rpy.

    Handles the dict tables and the list ones both -- BASE_SPELLS is a list,
    and assuming every table was a dict made this die on the second lookup.
    """
    m = re.search(r"^    %s = ([\{\[])" % re.escape(name), src, re.M)
    if not m:
        raise SystemExit("spec_check: no table named %s in combat.rpy" % name)
    close = "\n    %s\n" % ("}" if m.group(1) == "{" else "]")
    blob = src[m.start(1):]
    blob = blob[:blob.index(close) + len(close)]
    return eval(re.sub(r"^\s*#.*$", "", blob, flags=re.M), {"dict": dict})


def _moves_from(text):
    out = {}
    for d in re.finditer(r"dict\(([^)]*)\)", text):
        body = d.group(1)
        nm = re.search(r'name="([^"]+)"', body)
        if not nm:
            continue
        pw = re.search(r"power=(\d+)", body)
        pp = re.search(r"pp=(\d+)", body)
        out[norm(nm.group(1))] = (int(pw.group(1)) if pw else 0,
                                  int(pp.group(1)) if pp else None)
    return out


def engine(project):
    src = io.open(os.path.join(project, "game", "combat.rpy"),
                  encoding="utf-8").read()
    hp, moves, upgrade = {}, {}, {}
    fieldvals = {}          # (move name, field) -> the tier-II value

    # Moves the roster refers to by NAME rather than spelling out: the lists
    # (ASSASSIN_MOVES = [...]) and the single constants (GRASP = dict(...)),
    # because `moves=[CLAW, BITE]` is as common here as an inline literal.
    shared = {}
    for m in re.finditer(r"^    ([A-Z_]+_MOVES) = \[", src, re.M):
        shared[m.group(1)] = _moves_from(
            src[m.start():src.index("\n    ]\n", m.start())])
    for m in re.finditer(r"^    ([A-Z][A-Z_]*) = (dict\([^)]*\))", src, re.M):
        got = _moves_from(m.group(2))
        if got:
            shared[m.group(1)] = got

    # ⚠ ONE NAME, SEVERAL STATLINES. Enemies SCALE: the same assassins are
    # 10 HP early and 20 HP at the Act 1 boss, and a move keeps its name while
    # its damage grows. Keeping only the last Combatant call for a name would
    # report every earlier, correct figure as a mismatch. Each name therefore
    # holds the SET of values the engine uses anywhere, and a spec claim passes
    # if it matches one of them.
    calls = [(m.start(), m.group(1), int(m.group(2)))
             for m in re.finditer(r'Combatant\(\s*"([^"]+)"\s*,\s*(\d+)', src)]
    for k, (pos, name, health) in enumerate(calls):
        hp.setdefault(norm(name), set()).add(health)
        end = calls[k + 1][0] if k + 1 < len(calls) else len(src)
        body = src[pos:end]
        got = _moves_from(body)
        for ident in re.findall(r"\b([A-Z][A-Z_]{2,})\b", body):
            if ident in shared:
                got.update(shared[ident])
        slot = moves.setdefault(norm(name), {})
        for mv, stat in got.items():
            slot.setdefault(mv, set()).add(stat)

    # The player's own kit: base, plus what each technique grants and upgrades.
    kit = {}
    by_key = {}
    for spec in _literal(src, "BASE_SPELLS"):
        by_key[spec["key"]] = spec["name"]
        kit.setdefault(norm(spec["name"]), set()).add(
            (spec.get("power", 0), spec.get("pp")))
    for t in _literal(src, "TECHNIQUES").values():
        # tier I: what simply learning the technique does
        for key, fields in t.get("upgrades", {}).items():
            for f in ("guard_cut", "hold", "backlash"):
                if f in fields:
                    fieldvals.setdefault((None, key, f), set()).add(
                        round(float(fields[f]), 4))
        if "reflect" in t:
            fieldvals.setdefault((None, "wall", "reflect"), set()).add(t["reflect"])
        for g in t.get("grants", []):
            by_key[g["key"]] = g["name"]
            kit.setdefault(norm(g["name"]), set()).add(
                (g.get("power", 0), g.get("pp")))
        up = t.get("upgraded", {})
        for g in up.get("grants", []):
            by_key[g["key"]] = g["name"]
            kit.setdefault(norm(g["name"]), set()).add(
                (g.get("power", 0), g.get("pp")))
            upgrade[norm(g["name"])] = g.get("power", 0)
        for key, fields in up.get("upgrades", {}).items():
            nm = norm(by_key.get(key, key))
            if "power" in fields:
                upgrade[nm] = fields["power"]
            for f in ("guard_cut", "hold", "backlash"):
                if f in fields:
                    fieldvals.setdefault((None, key, f), set()).add(
                        round(float(fields[f]), 4))
        if "reflect" in up:
            fieldvals.setdefault((None, "wall", "reflect"), set()).add(up["reflect"])
    # re-key from the spell KEY onto the spell NAME, now that every technique
    # has contributed its grants to by_key.
    fieldvals = {(norm(by_key.get(k, k)), f): v
                 for (_, k, f), v in fieldvals.items()}
    for beast in _literal(src, "SUMMONS").values():
        for mv in beast["moves"]:
            kit.setdefault(norm(mv["name"]), set()).add(
                (mv.get("power", 0), mv.get("pp")))
    moves[PLAYER] = kit

    php = re.search(r"^default player_max_hp = (\d+)", src, re.M)
    if php:
        hp[PLAYER] = {int(php.group(1))}
    return hp, moves, upgrade, fieldvals


# ------------------------------------------------------------------ the spec

HP_EACH = re.compile(r"^(.+?)\s*\(\d+\),\s*each with\s*(\d+)\s*HP", re.I)
HP_ONE = re.compile(r"^(.+?),\s*(\d+)\s*HP\b", re.I)
HP_HAS = re.compile(r"^(.+?)\s+has\s+(\d+)\s*HP\b", re.I)
NAMED = re.compile(r"^([A-Z][\w'’#\- ]{1,34}?)\s*\(([^)]*)\)")
BARE = re.compile(r"^\(([^)]*)\)\s*$")
PP_ONLY = re.compile(r"^(\d+)\s*PP\s*$", re.I)
DMG_ONLY = re.compile(r"^(\d+)\s*damage\b", re.I)
UNLOCK = re.compile(r"^New technique unlocked:\s*([^(]+?)\s*\(([^)]*)\)", re.I)
INCREASE = re.compile(r"^(.+?)\s+increases to\s+(\d+)\s*damage", re.I)
# The tier-II lines that state a PERCENTAGE or a flat reflect, each mapped to
# the field in TECHNIQUES that carries it.
PCTS = (
    (re.compile(r"damage reduction increased to\s*(\d+)\s*%", re.I),
     "guard_cut", lambda v: round(1.0 - v / 100.0, 4)),
    (re.compile(r"freeze effect increases to\s*(\d+)\s*%", re.I),
     "hold", lambda v: round(v / 100.0, 4)),
    (re.compile(r"recoil is reduced to\s*(\d+)\s*%", re.I),
     "backlash", lambda v: round(v / 100.0, 4)),
    (re.compile(r"reflects\s*(\d+)\s*damage", re.I),
     "reflect", lambda v: v),
)
NAMEY = re.compile(r"^[A-Z][A-Za-z'’#\- ]{1,34}$")


def _stats(inside):
    """(damage, pp) out of a parenthetical, in whatever order they appear."""
    d = re.search(r"(\d+)\s*damage", inside, re.I)
    p = re.search(r"(\d+)\s*?PP", inside, re.I)
    return (int(d.group(1)) if d else None, int(p.group(1)) if p else None)


def claims(docx_path, patterns):
    import docx
    script_diff.load_patterns(patterns)
    paras = [p.text.strip() for p in docx.Document(docx_path).paragraphs]
    prose = script_diff.prose_mask(paras)
    spec = [(i, t) for i, (t, pr) in enumerate(zip(paras, prose)) if t and not pr]

    found, unread = [], []
    owner = PLAYER
    for n, (i, whole) in enumerate(spec):
        for line in [l.strip() for l in whole.splitlines() if l.strip()]:
            if not re.search(r"\d", line):
                # A bare name line re-owns nothing, but it is the move label
                # the PP/damage lines below refer to.
                continue
            m = HP_EACH.match(line) or HP_HAS.match(line) or HP_ONE.match(line)
            if m and "damage" not in line.lower() and "PP" not in line:
                who = m.group(1).strip()
                owner = who
                for one in re.split(r"\s+and\s+", who):
                    found.append(("hp", one.strip(), int(m.group(2)), i))
                continue
            m = UNLOCK.match(line)
            if m:
                found.append(("upgrade_move", m.group(1).strip(),
                              _stats(m.group(2)), i))
                continue
            m = INCREASE.match(line)
            if m:
                found.append(("upgrade", m.group(1).strip(), int(m.group(2)), i))
                _pcts(found, line, i)
                continue
            hit = _pcts(found, line, i)
            if hit:
                continue
            m = NAMED.match(line)
            if m and re.search(r"\d", m.group(2)):
                dmg, pp = _stats(m.group(2))
                if dmg is not None or pp is not None:
                    found.append(("move", (owner, m.group(1).strip()), (dmg, pp), i))
                    continue
            m = BARE.match(line)
            if m:
                nm = _name_above(spec, n)
                dmg, pp = _stats(m.group(1))
                if nm and (dmg is not None or pp is not None):
                    found.append(("move", (owner, nm), (dmg, pp), i))
                else:
                    unread.append((i, line))
                continue
            m = PP_ONLY.match(line)
            if m:
                nm = _name_above(spec, n)
                dmg = _damage_below(spec, n)
                if nm:
                    found.append(("move", (owner, nm), (dmg, int(m.group(1))), i))
                else:
                    unread.append((i, line))
                continue
            if DMG_ONLY.match(line):
                continue                      # consumed by its PP line above
            unread.append((i, line))
    return found, unread


def _pcts(found, line, para):
    """Percentage and reflect claims on a tier-II line, with the move they
    belong to -- which is whatever the line starts with."""
    who = re.match(r"^([A-Z][\w'\u2019 ]{1,30}?)(?:\s+(?:increases|now|s\b)|\u2019s\b)",
                   line)
    owner = who.group(1).strip() if who else None
    got = False
    for rx, field, conv in PCTS:
        m = rx.search(line)
        if m:
            found.append(("field", (owner, field), conv(int(m.group(1))), para))
            got = True
    return got


def _name_above(spec, n):
    for k in range(n - 1, max(-1, n - 4), -1):
        cand = spec[k][1].splitlines()[0].strip()
        if NAMEY.match(cand) and not re.search(r"\d", cand):
            return cand
    return None


def _damage_below(spec, n):
    for k in range(n + 1, min(len(spec), n + 3)):
        m = DMG_ONLY.match(spec[k][1].splitlines()[0].strip())
        if m:
            return int(m.group(1))
    return None


# ------------------------------------------------------------------- compare

def _find_owner(hp_map, moves, who):
    """Match a spec roster name to the engine's combatants.

    The author writes "Bandits (3), each with 5 HP" for three Combatants named
    "Bandit #1..#3", so an exact lookup finds nothing. Falls back to any engine
    name that starts with the singular.
    """
    out = []
    # "Assassin #1 and Assassin #2, 20 HP each" names two combatants at once.
    for part in re.split(r"\s+and\s+", who):
        k = norm(part)
        if k in moves:
            out.append(k)
            continue
        # "Bandits (3), each with 5 HP" against Combatants "Bandit #1..#3".
        stem = k[:-1] if k.endswith("s") else k
        out += [n for n in moves if n.startswith(stem) and n != PLAYER]
    return out


def main(docx_path, project, patterns):
    hp, moves, upgrade, fieldvals = engine(project)
    found, unread = claims(docx_path, patterns)
    ok, bad, nomatch = 0, [], []

    for kind, key, value, para in found:
        if kind == "hp":
            owners = _find_owner(hp, moves, key)
            if not owners:
                nomatch.append(("HP", key, value, para))
            else:
                seen = set()
                for who in owners:
                    seen |= hp.get(who, set())
                if value in seen:
                    ok += 1
                else:
                    bad.append(("HP", key, value, sorted(seen), para))
        elif kind == "field":
            owner, field = key
            if owner is None:
                nomatch.append((field, "?", value, para)); continue
            have = fieldvals.get((norm(owner), field))
            if not have:
                hits = [v for (k2, f2), v in fieldvals.items()
                        if f2 == field and k2.endswith(norm(owner))]
                have = hits[0] if len(hits) == 1 else None
            if not have:
                nomatch.append((field, owner, value, para))
            elif any(abs(h - value) < 1e-6 for h in have):
                ok += 1
            else:
                bad.append((field, owner, value, sorted(have), para))
        elif kind == "upgrade":
            have = upgrade.get(norm(key))
            if have is None:
                hits = [v for k2, v in upgrade.items() if k2.endswith(norm(key))]
                have = hits[0] if len(hits) == 1 else None
            if have is None:
                nomatch.append(("upgraded damage", key, value, para))
            elif have == value:
                ok += 1
            else:
                bad.append(("upgraded damage", key, value, have, para))
        elif kind == "upgrade_move":
            have = moves[PLAYER].get(norm(key))
            if not have:
                nomatch.append(("new technique", key, value, para))
            elif any(_agree(value, v) for v in have):
                ok += 1
            else:
                bad.append(("new technique damage/PP", key, value,
                            sorted(have), para))
        else:
            who, mv = key
            owners = _find_owner(hp, moves, who) or [PLAYER]
            have = set()
            for o in owners:
                have |= moves.get(o, {}).get(norm(mv), set())
            if not have:
                have = _player_move(moves, mv)
            if not have:
                nomatch.append(("move", "%s / %s" % (who, mv), value, para))
            elif any(_agree(value, v) for v in have):
                ok += 1
            else:
                bad.append(("move damage/PP", "%s / %s" % (who, mv),
                            value, sorted(have), para))

    print("spec_check: %d numeric claim(s) read from the spec" % len(found))
    print("  agree with the engine : %d" % ok)
    print("  DISAGREE              : %d" % len(bad))
    print("  no engine counterpart : %d" % len(nomatch))
    print("  spec lines not parsed : %d" % len(unread))
    for what, name, want, have, para in bad:
        print("\nMISMATCH  %s of %s" % (what, name))
        print("   script (para %d) says : %s" % (para, want))
        print("   combat.rpy uses      : %s" % (have,))
    if nomatch:
        print("\nNO COUNTERPART IN combat.rpy "
              "(a name the engine spells differently, or not wired yet):")
        for what, name, want, para in nomatch:
            print("  para %-5d %-16s %s = %s" % (para, what, name, want))
    if unread:
        print("\nNOT PARSED -- numeric spec lines this tool does not read:")
        for para, line in unread:
            print("  para %-5d %s" % (para, line[:86]))
    return 1 if bad else 0


def _player_move(moves, name):
    """The player's move, allowing the script's shorter spelling of it.

    A script commonly writes the short name of a move ("Sword Strike") where
    the engine qualifies it ("<Style> Sword Strike"), because on the command
    grid it has to be told apart from other styles' strikes. Only an
    UNAMBIGUOUS suffix match counts -- if two of the player's moves could end
    that way, this returns nothing rather than guessing.
    """
    k = norm(name)
    kit = moves[PLAYER]
    if k in kit:
        return kit[k]
    hits = [v for k2, v in kit.items() if k2.endswith(k)]
    return hits[0] if len(hits) == 1 else set()


def _agree(want, have):
    """Compare only the fields the spec actually stated."""
    wd, wp = want
    hd, hp_ = have
    return ((wd is None or wd == hd) and (wp is None or wp == hp_))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: python spec_check.py <master.docx> "
                         "<project-dir> [patterns.json]")
    pats = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        sys.argv[2], "game", "patterns.json")
    sys.exit(main(sys.argv[1], sys.argv[2], pats))
