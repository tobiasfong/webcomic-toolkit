"""Locate the visual novel's game tree without naming the project.

⚠ THIS DIRECTORY IS TRACKED AND THE REPOSITORY IS PUBLIC. The project slug and
every character name are private, so no tool in here may hardcode a path into
the game tree. They take it as an argument instead.

Resolution order:
  1. the first command-line argument
  2. the VN_GAME_DIR environment variable
  3. give up with a usage message -- never guess

Point it at the `game/` directory itself, or at the project directory that
contains it; both work.
"""
import os
import sys


def game_dir(argv=None, required=True):
    """Return the game/ directory these tools should read and write."""
    argv = sys.argv[1:] if argv is None else argv
    raw = argv[0] if argv else os.environ.get("VN_GAME_DIR")

    if not raw:
        if not required:
            return None
        sys.exit(
            "No game directory given.\n"
            "  usage: python %s <path-to-game-dir>\n"
            "  or set VN_GAME_DIR in the environment.\n"
            "The path is deliberately not stored in this repository."
            % os.path.basename(sys.argv[0])
        )

    path = os.path.abspath(raw)
    # Accept the project directory as a convenience.
    if not os.path.basename(path) == "game" and os.path.isdir(os.path.join(path, "game")):
        path = os.path.join(path, "game")

    if not os.path.isdir(path):
        sys.exit("Not a directory: %s" % path)
    return path


def out_dir(game, *parts):
    """A subdirectory of the game tree, created if it does not exist."""
    p = os.path.join(game, *parts)
    os.makedirs(p, exist_ok=True)
    return p
