"""Install this server's ComfyUI add-on (comfy_nodes/ace_extend) into ComfyUI's custom_nodes folder.

    python tools/install_comfy_nodes.py [ComfyUI root]

The root defaults to WEBCOMIC_MUSIC_COMFY_DIR (the portable install that holds ComfyUI/). The add-on is COPIED,
not linked (a Windows symlink needs admin rights), so rerun this after editing comfy_nodes/. ComfyUI must be
restarted afterward to load it; check_status reports whether the running ComfyUI has it.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "comfy_nodes", "ace_extend")
NAME = "music_mcp_ace_extend"


def install(comfy_root: str) -> str:
    nodes = os.path.join(comfy_root, "ComfyUI", "custom_nodes")
    if not os.path.isdir(nodes):
        nodes = os.path.join(comfy_root, "custom_nodes")      # a non-portable install points straight at ComfyUI/
    if not os.path.isdir(nodes):
        raise SystemExit(f"No custom_nodes folder under {comfy_root}")
    dst = os.path.join(nodes, NAME)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WEBCOMIC_MUSIC_COMFY_DIR",
                                                                  r"C:\AI\ComfyUI_windows_portable")
    print("installed:", install(root), "-- restart ComfyUI to load it")
