## touch_input.rpy -- drop into game/ to give a screen an honest answer to
## "does this device have hover?", and a pattern for command buttons that
## need it.
##
## WHY THIS EXISTS. A visual novel with a combat or command menu shows a
## move's stats on HOVER and uses it on CLICK. A phone has no hover, so the
## stats have no way to appear and the first tap uses the move. The fix is
## two taps -- the first arms and highlights a move and shows its stats, the
## second on the highlighted move uses it -- and it must switch on by
## itself. NEVER expose it as a preference: desktop would inherit a choice
## that means nothing there, and a phone reader who cannot see the stats
## will not guess that a setting exists to fix it. The game accommodates the
## device from the start, or it has failed.
##
## WHY NOT renpy.variant("touch"). The engine's touch and mobile variants
## come from how the browser identifies itself, and on a real phone they
## were found NOT set while every other phone feature worked. The browser
## itself knows the actual question -- can the main input hover? -- as the
## CSS media query (hover: none): true on phones and tablets, false wherever
## a mouse is present. On the web build that is asked once over the
## emscripten bridge and cached; off the web, the touch variant stands in.
##
## ⚠ ON TOUCH A TAP ARRIVES AS HOVER, THEN CLICK. If the button's `hovered`
## action is allowed to arm the move, the screen re-evaluates and the click
## of the SAME tap lands on an armed button and uses it -- the single tap
## still fires, and it looks as if the two-tap rule never engaged. On touch
## the hover must do nothing.

init python:
    _touch_only = None

    def touch_only():
        """True when the device's main input cannot hover. Asked once."""
        global _touch_only
        if _touch_only is None:
            try:
                import emscripten
                _touch_only = bool(emscripten.run_script_int(
                    "(window.matchMedia && window.matchMedia('(hover: none)').matches) ? 1 : 0"))
            except Exception:
                _touch_only = renpy.variant("touch")
        return _touch_only


## THE PATTERN, for a command menu called with `call screen`:
##
##   screen command_menu(moves):
##       default armed = (None if touch_only() else moves[0])
##       vpgrid:
##           for m in moves:
##               textbutton "[m.name]":
##                   style "cmd_button"      # give it a selected_background:
##                                           # the armed move must LOOK armed
##                   action ((Return(m) if armed is m else SetLocalVariable("armed", m))
##                           if touch_only() else Return(m))
##                   selected (touch_only() and armed is m)
##                   hovered (NullAction() if touch_only() else SetLocalVariable("armed", m))
##       frame:
##           if armed is not None:
##               text "[armed.summary]"
##           else:
##               text _("Tap a move to check it. Tap the highlighted move to use it.")
##
## The style's `hover_background` is what the mouse shows; set the SAME
## frame as `selected_background`, or arming is invisible on the phone.
