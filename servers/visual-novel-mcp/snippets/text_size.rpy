## text_size.rpy -- a Text Size preference in three states, and the two
## things every screen must do for it to hold.
##
## WHY THREE STATES, NOT A SLIDER. Phones differ in physical size, so the
## reader picks; three fixed states (the default, a big and a biggest) are
## better than a continuum because each one can be checked on every screen,
## and a reader picks in one tap. The engine's own scaling factor,
## `_preferences.font_size`, multiplies EVERY piece of text, so the states
## are ratios of the body text size: for a 34 px body, 40 and 48 are
## 40.0/34.0 and 48.0/34.0. `_DisplayReset()` applies the change.
##
## Put this inside the Preferences screen, beside the other sliders:
##
##   label _("Text Size")
##   hbox:
##       style_prefix "radio"
##       spacing 24
##       textbutton _("Default") action [SetField(_preferences, "font_size", 1.0), _DisplayReset()] selected (abs(_preferences.font_size - 1.0) < 0.01)
##       textbutton _("Big")     action [SetField(_preferences, "font_size", 40.0 / 34.0), _DisplayReset()] selected (abs(_preferences.font_size - 40.0 / 34.0) < 0.01)
##       textbutton _("Biggest") action [SetField(_preferences, "font_size", 48.0 / 34.0), _DisplayReset()] selected (abs(_preferences.font_size - 48.0 / 34.0) < 0.01)
##
## ⚠ THE FACTOR SCALES TEXT, NOT BOXES. Every screen with a size in pixels
## breaks at the larger states unless it reads the factor: a name wraps past
## the bottom of a card, a description runs off the screen, rows of a fixed
## height overlap, a long button label wraps into the row below it, and a
## highlight frame wraps half of a two-row label. Measured on one project,
## all of those happened at 1.41 and none at 1.0. The rule:
##
##   $ f = min(_preferences.font_size, 1.45)          # cap where the box would leave the screen
##   frame:
##       xsize int(600 * f)                            # widths and heights follow the factor
##       ysize int(470 * f)
##   ...
##   textbutton "[item.name]":
##       ysize int(62 * f)                             # fixed rows too, or they overlap
##
## A grid that must keep its footprint (a command box that sits in a fixed
## place) switches to ONE wide column above ~1.15x with rows sized to the
## text, and scrolls for the rest; images inside a box give back what the
## text takes (zoom by 1/f). An offset between a name and its dialogue that
## is a fixed number in the style must scale too, or the name grows into the
## line below it.
##
## ⚠ NVL PAGES ARE NEARLY FULL AT 1.0. Measure before offering any larger
## text: on one project the tallest page stood at 925 of the 1010 px above
## the quick menu, so a 5% increase already ran into the menu. Rather than
## show fewer entries, put the entries in a viewport opened at the bottom,
## so the newest line is always in view and a taller page is read by
## dragging up. Drag only: the mouse wheel keeps its rollback meaning.
##
##   viewport:
##       ymaximum 990                                  # the space above the quick menu
##       yinitial 1.0
##       draggable True
##       mousewheel False
##       arrowkeys False
##       vbox:
##           use nvl_dialogue(dialogue)
##
## And the quick menu itself: with `box_wrap True` its buttons wrap to a
## second row instead of the last one falling off the right edge, which
## otherwise leaves History as the only door into the game menu.
