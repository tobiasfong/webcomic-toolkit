"""
Music Generation — MCP Server
=============================
Local BGM and vocal theme-song generation for the webcomic/anime pipeline, via
ComfyUI's native ACE-Step support. Closes the last outsourced step in the video
pipeline: the anime-production skill has always *played* an mp3 but never made
one, and the mp3 came from Suno — a paid cloud service, the exact dependency
this ecosystem exists to avoid (ARCHITECTURE.md §7a).

Runs on the same 6 GB RTX 3060 Laptop as the other GPU servers. No custom
ComfyUI nodes are required: ACE-Step 1.0 and 1.5 are both in ComfyUI core as of
0.25. Contrast the LTX install, which needed third-party GGUF loaders.

Scope guard (§7a): generation and beat analysis ONLY. Mixing, mastering and stem
separation are a different product — if those appear, stop and split.

Exposes: generate_track, generate_variations, list_tracks, get_track,
extract_beats, check_status.

Usage discipline, taught here because the §8a lesson says the server must teach
it rather than let it be discovered the hard way:

  * ComfyUI runs prompts SERIALLY. Submit one generation at a time; a stacked
    job just burns its timeout waiting in the queue.
  * Songs need AUDITIONING — one take is never enough. Generate, listen, then
    generate_variations on the take that was closest. The reviewer is the
    author's ears; the model does not need to "listen back", so iteration costs
    GPU-minutes (free, local) rather than tokens.
  * A track is reproducible from its recipe. Keep the id, not the parameters.
"""

import os

from mcp.server.fastmcp import FastMCP

import ace_workflow as aw
import comfy
import tracks as tk
from tools import beats


BASE = os.path.dirname(os.path.abspath(__file__))

mcp = FastMCP("music-generator")


def _fetch_outputs(outs: dict, project: str, track_id: str) -> dict[str, str]:
    """Pull the FLAC and MP3 that one graph produced into the track folder."""
    d = tk.track_dir(project, track_id)
    os.makedirs(d, exist_ok=True)
    files: dict[str, str] = {}
    for refs in outs.values():
        for ref in refs:
            ext = os.path.splitext(ref["filename"])[1].lower().lstrip(".")
            if ext not in ("flac", "mp3", "opus", "wav"):
                continue
            dest = os.path.join(d, f"{track_id}.{ext}")
            comfy.fetch(ref, dest)
            files[ext] = dest
    if not files:
        raise comfy.ComfyUIError("ComfyUI returned outputs but none were audio files.")
    return files


def _generate(project: str, title: str, params: dict) -> dict:
    track_id = tk.new_track_id(project, title)
    graph = aw.build_graph(filename_prefix=f"audio/{track_id}", **params)
    outs = comfy.submit_and_wait(graph)
    files = _fetch_outputs(outs, project, track_id)
    return tk.record(project, track_id, title, aw.recipe(**params), files)


@mcp.tool()
def generate_track(
    project: str,
    title: str,
    tags: str,
    lyrics: str = "",
    duration: float = 120.0,
    language: str = "en",
    bpm: int = 120,
    keyscale: str = "C major",
    timesignature: str = "4",
    seed: int = 0,
    variant: str = "1.5",
    steps: int | None = None,
    cfg: float | None = None,
    reference_audio_path: str | None = None,
) -> dict:
    """Generate one track. Blocking; minutes on a 6 GB card.

    tags: comma-separated style/instrumentation, e.g.
      "j-pop, anime opening, female vocal, piano, strings, driving drums".
    lyrics: leave empty for instrumental BGM. Section markers ([verse],
      [chorus]) help structure. Set `language` to match ("ja" for Japanese).
    bpm/keyscale/timesignature/language apply to variant "1.5" only; "1.0" takes
      tags and lyrics alone.
    reference_audio_path: local audio whose timbre/voice to steer toward (1.5,
      experimental). Supplying one disables the audio-code LLM, per ComfyUI.

    Returns the track record, including paths to a lossless .flac and a .mp3
    ready for the Remotion pipeline.
    """
    params = dict(
        tags=tags, lyrics=lyrics, duration=duration, seed=seed, variant=variant,
        bpm=bpm, language=language, keyscale=keyscale, timesignature=timesignature,
        steps=steps, cfg=cfg,
    )
    if reference_audio_path:
        if not os.path.isfile(reference_audio_path):
            raise FileNotFoundError(f"reference_audio_path not found: {reference_audio_path}")
        params["reference_audio"] = comfy.upload_audio(reference_audio_path)
    return _generate(project, title, params)


@mcp.tool()
def generate_variations(track_id: str, n: int = 3, seed_step: int = 1000) -> list[dict]:
    """Re-run an existing track's recipe under new seeds — the audition loop.

    Runs SEQUENTIALLY (ComfyUI is serial anyway, and batching long audio on a
    6 GB card invites an OOM). n=3 at 120s is roughly 15-30 minutes; keep n
    small and duration short while hunting for a direction.
    """
    rec = tk.get(track_id)
    if rec is None:
        raise ValueError(f"No such track: {track_id}. Use list_tracks.")
    if not 1 <= n <= 8:
        raise ValueError("n must be 1-8; audition a few takes at a time.")

    base = dict(rec["recipe"])
    base_seed = int(base.get("seed", 0))
    out = []
    for i in range(1, n + 1):
        params = dict(base, seed=base_seed + i * seed_step)
        out.append(_generate(rec["project"], rec["title"], params))
    return out


@mcp.tool()
def list_tracks(project: str | None = None) -> dict:
    """Terse listing of generated tracks (id, title, duration, mp3 path).
    Call get_track for one track's full recipe."""
    return {"projects": tk.projects(), "tracks": tk.listing(project)}


@mcp.tool()
def get_track(track_id: str) -> dict:
    """One track's full record: every generation parameter, plus file paths."""
    rec = tk.get(track_id)
    if rec is None:
        raise ValueError(f"No such track: {track_id}. Use list_tracks.")
    return rec


@mcp.tool()
def approve_track(track_id: str, slug: str | None = None) -> dict:
    """Lock a take as the project's canon and publish it under a stable name.

    Copies it to `FINAL_<slug>.mp3` / `.flac` (plus its beat grid) at the project
    root, so downstream tools reference one obvious file instead of a timestamped
    track id. Marks every other take unapproved. `forget_track` then refuses to
    delete this one.
    """
    return tk.approve(track_id, slug)


@mcp.tool()
def forget_track(track_id: str) -> dict:
    """Delete a take's audio and its manifest entry. Refuses the approved one."""
    return {"forgotten": tk.forget(track_id), "track_id": track_id}


@mcp.tool()
def extract_beats(track_id: str | None = None, audio_path: str | None = None,
                  bpm: int | None = None) -> dict:
    """Beat grid + energy envelope, so video cuts land on downbeats.

    Pass a track_id (analyses its mp3, attaches beats.json to the record) or an
    arbitrary audio_path. `bpm` skips tempo detection — pass it for tracks this
    server generated, where bpm was an INPUT and is therefore already known.

    Pure Python: no Node, no ffmpeg.
    """
    if not (track_id or audio_path):
        raise ValueError("Pass either track_id or audio_path.")
    rec = None
    if track_id:
        rec = tk.get(track_id)
        if rec is None:
            raise ValueError(f"No such track: {track_id}. Use list_tracks.")
        audio_path = rec["files"].get("mp3") or rec["files"].get("flac")
        out_path = os.path.join(tk.track_dir(rec["project"], track_id), "beats.json")
    else:
        out_path = os.path.splitext(audio_path)[0] + "_beats.json"
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    # ALWAYS measure, even when the recipe states a bpm. The requested tempo is
    # not what the model necessarily renders: a track asked for 120 came back at
    # a measured 117.45, and building the grid from 120 put every downbeat
    # progressively wrong — 0.78 s adrift by the 30 s mark, close to half a bar.
    # An earlier version of this preferred the recipe on the reasoning that
    # "tempo was an input, so detection can only lose information". That is only
    # true if the model obeys, and it does not reliably.
    measured = beats.analyse(audio_path, known_bpm=None)
    requested = bpm if bpm is not None else (rec or {}).get("recipe", {}).get("bpm")

    out = beats.write(audio_path, out_path, known_bpm=bpm)  # bpm=None -> detected
    if rec:
        tk.attach(track_id, "beats", out_path)

    result = {
        "beats_json": out_path,
        "bpm": out["bpm"],
        "measured_bpm": measured["bpm"],
        "requested_bpm": requested,
        "beat_count": len(out["beats"]),
        "downbeat_count": len(out["downbeats"]),
        "onset_count": len(out["onsets"]),
    }
    if requested and abs(measured["bpm"] - requested) > 1.0:
        drift = abs(measured["beatInterval"] - 60.0 / requested) * len(out["beats"])
        result["warning"] = (
            f"Rendered tempo ({measured['bpm']:.2f}) differs from the requested "
            f"{requested}. Cutting to a {requested} BPM grid would drift ~{drift:.2f}s "
            f"across this track. This grid uses the MEASURED tempo — verify by ear."
        )
    return result


@mcp.tool()
def check_status() -> dict:
    """Is the GPU path usable? Reports ComfyUI reachability, VRAM, and which
    ACE-Step model files each variant is missing. Call this first when a
    generation fails."""
    status: dict = {"comfy_url": comfy.COMFY_URL, "comfy_running": comfy.comfy_is_up()}
    if not status["comfy_running"]:
        status["hint"] = ("Start ComfyUI (it auto-launches on first generate) — "
                          f"{comfy.COMFY_DIR}\\{comfy.COMFY_LAUNCH}")
        return status

    stats = comfy.system_stats()
    dev = (stats.get("devices") or [{}])[0]
    status["device"] = dev.get("name")
    status["vram_total_gb"] = round(dev.get("vram_total", 0) / 1e9, 2)
    status["comfyui_version"] = stats.get("system", {}).get("comfyui_version")

    present = {f: set(comfy.list_models(f))
               for f in ("diffusion_models", "text_encoders", "vae", "checkpoints")}
    v15, v10 = aw.VARIANTS["1.5"], aw.VARIANTS["1.0"]
    missing_15 = [n for n, f in ((v15["unet"], "diffusion_models"),
                                 (v15["clip1"], "text_encoders"),
                                 (v15["clip2"], "text_encoders"),
                                 (v15["vae"], "vae")) if n not in present[f]]
    status["variants"] = {
        "1.5": {"ready": not missing_15, "missing": missing_15},
        "1.0": {"ready": v10["checkpoint"] in present["checkpoints"],
                "missing": [] if v10["checkpoint"] in present["checkpoints"]
                           else [v10["checkpoint"]]},
    }
    if missing_15:
        status["hint"] = ("Missing model files. NOTE: ComfyUI caches some folder "
                          "listings at startup — if you just downloaded these, "
                          "restart ComfyUI before trusting this list.")
    status["output_root"] = tk.OUTPUT_ROOT
    return status


if __name__ == "__main__":
    mcp.run()
