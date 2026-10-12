# -*- coding: utf-8 -*-
"""Combat data for the story map demo.

story_map.py calls combat_data(project_dir) and draws whatever comes back.
It does no arithmetic of its own, on purpose: in YOUR game, compute these
numbers with the game's own combat code (import it, or load your combat
.rpy's Python the way your test harness does), so the page and the game can
never disagree. Here the "engine" is the small set of tables below, standing
in for that code.
"""

# --- the stand-in engine: base commands, skill tiers, weapons ------------
COMMANDS = [
    {"name": "Slash", "pp": 20, "damage": 10},
    {"name": "Fire Bolt", "pp": 10, "damage": 15},
    {"name": "Guard", "pp": 10, "damage": 0, "effect": "takes 50% less this turn"},
]
SKILL = {   # the skill a player learns; "upgraded" adds to "learned"
    "": {},
    "learned": {"Slash": 5},
    "upgraded": {"Slash": 10, "Fire Bolt": 10},
}
WEAPONS = {
    "": {"name": "none", "bonus": 0},
    "iron": {"name": "Iron sword", "bonus": 5},
    "flame": {"name": "Flame sword", "bonus": 8, "effect": "+burn on Fire Bolt"},
}


def finished_kit(skill, weapon):
    """The player's commands as a fight would use them -- the one place the
    arithmetic lives, the way your engine's own function would."""
    rows, w = [], WEAPONS[weapon]
    for c in COMMANDS:
        dmg = c["damage"]
        effect = c.get("effect", "")
        if dmg:
            dmg += SKILL[skill].get(c["name"], 0) + w["bonus"]
            if c["name"] == "Fire Bolt" and w.get("effect"):
                effect = w["effect"]
        rows.append([c["name"], c["pp"], str(dmg) if dmg else "—", effect])
    notes = ["weapon: %s" % w["name"]] + (["skill tier: " + skill] if skill else [])
    return {"rows": rows, "notes": notes}


def combat_data(project_dir):
    return {
        "fights": {
            "battle_wolves": {
                "title": "Wolves at the ford",
                "enemies": [{"name": "Wolf", "count": 2, "hp": 20,
                             "moves": [{"name": "Bite", "pp": 20, "damage": "8", "effect": ""},
                                       {"name": "Howl", "pp": 5, "damage": "0",
                                        "effect": "the pack's next bites +2"}]}],
            },
            "battle_bandit_chief": {
                "title": "The bandit chief",
                "enemies": [{"name": "Bandit chief", "hp": 60,
                             "moves": [{"name": "Cleave", "pp": 10, "damage": "18", "effect": ""},
                                       {"name": "Dirty Trick", "pp": 5, "damage": "6",
                                        "effect": "25% chance to stun"}]},
                            {"name": "Bandit", "count": 2, "hp": 15,
                             "moves": [{"name": "Stab", "pp": 20, "damage": "6", "effect": ""}]}],
                "notes": ["boss music"],
            },
        },
        "tables": [{
            "title": "Player commands, base",
            "columns": ["Command", "PP", "Damage", "Effect"],
            "rows": [[c["name"], c["pp"], c["damage"] or "—", c.get("effect", "")] for c in COMMANDS],
        }],
        "calculator": {
            "title": "The player's kit, finished",
            "axes": [
                {"id": "skill", "label": "Skill",
                 "options": [["", "not learned"], ["learned", "learned"], ["upgraded", "upgraded"]]},
                {"id": "weapon", "label": "Weapon",
                 "options": [[k, v["name"]] for k, v in WEAPONS.items()]},
            ],
            "columns": ["Command", "PP", "Damage", "Effect"],
            # keyed by the axis values in axis order, joined by "|"
            "results": {"%s|%s" % (s, w): finished_kit(s, w) for s in SKILL for w in WEAPONS},
        },
    }
