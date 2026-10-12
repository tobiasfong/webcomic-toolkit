# A tiny made-up visual novel, here only to show what story_map.py draws.
# Two companions, a few choices, two fights. Every name and number is invented.

define a = Character("Ayla")
define m = Character("Mira")

default ayla_affection = 0
default mira_affection = 0
default took_the_map = False
default player_max_hp = 100

label start:
    "The caravan leaves at dawn. Ayla checks the wagons; Mira studies the map."
    jump ch1_road

label ch1_road:
    "A fork in the road. The river path is shorter, the ridge path safer."
    menu:
        "Take the river path, as Ayla suggests.":
            $ ayla_affection += 10
            jump ch1_river
        "Take the ridge path, as Mira suggests.":
            $ mira_affection += 10
            jump ch1_ridge

label ch1_river:
    "Wolves wait at the ford."
    call battle_wolves
    $ ayla_affection += 5
    jump ch1_camp

label ch1_ridge:
    "The ridge is quiet, and Mira finds an old map in a cairn."
    $ took_the_map = True
    jump ch1_camp

label ch1_camp:
    "That night, by the fire."
    menu:
        "Thank Ayla for keeping watch.":
            $ ayla_affection += 10
        "Ask Mira about the map.":
            $ mira_affection += 15
        "Say nothing and sleep.":
            pass
    $ player_max_hp = 120
    jump ch2_gate

label ch2_gate:
    "The bandit chief blocks the city gate."
    call battle_bandit_chief
    menu:
        "Spare him.":
            $ ayla_affection += 5
            $ mira_affection -= 5
        "Hand him to the guard.":
            $ mira_affection += 5
    "The gate opens. End of the demo."
    return

# The fights. A real game runs its combat here; the demo only returns.
label battle_wolves:
    return

label battle_bandit_chief:
    return
