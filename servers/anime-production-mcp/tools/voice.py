"""
voice.py: Japanese dialogue lines from a local VOICEVOX engine, as .wav files.

JAPANESE ONLY. VOICEVOX is a Japanese text-to-speech engine. Voiced videos carry
Japanese audio, with English subtitles (subs.py) where needed.

THE ENGINE. The VOICEVOX app runs its speech engine as a local HTTP server on
port 50021 while it is open. If nothing answers there, `ensure_engine()` starts
the engine on its own (`vv-engine/run.exe --use_gpu`) and waits for it. The
engine is found from WEBCOMIC_VOICEVOX_ENGINE (the path to run.exe), or the
winget install location.

TWO CALLS PER LINE. `audio_query` turns the text into an editable prosody plan
(accents, pauses, timing); `synthesis` renders that plan. The plan's speed,
pitch, intonation and volume scales are the knobs a director needs, so `say()`
exposes them and leaves the rest at the voice's defaults.

LICENSING, which must travel with every video that uses it:
- The VOICEVOX software is free for commercial and non-commercial use, and
  always needs a credit.
- Each character voice has its OWN terms on top. The common form of the credit
  is `VOICEVOX:<character>` (for example `VOICEVOX:四国めたん`), in the
  description or the end credits. `credits()` builds those lines for the voices
  a video used. Read a character's terms before its first use. Some voices'
  owners ban political or religious content, misleading content, and certain
  businesses.

Standard library only (urllib), so it runs in any of the servers' venvs.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("WEBCOMIC_VOICEVOX_URL", "http://127.0.0.1:50021")
_DEFAULT_ENGINE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
    "HiroshibaKazuyuki.VOICEVOX_Microsoft.Winget.Source_8wekyb3d8bbwe", "VOICEVOX", "vv-engine", "run.exe")
ENGINE = os.environ.get("WEBCOMIC_VOICEVOX_ENGINE", _DEFAULT_ENGINE)


def _get(path: str, timeout: float = 10):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, params: dict, body: bytes | None = None, timeout: float = 120) -> bytes:
    url = HOST + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=body if body is not None else b"", method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def engine_version() -> str | None:
    """The running engine's version, or None if nothing answers."""
    try:
        return _get("/version", timeout=2)
    except (urllib.error.URLError, OSError):
        return None


def ensure_engine(wait_s: float = 120) -> str:
    """Make sure an engine is answering; start one (on the GPU) if not. Returns its version."""
    v = engine_version()
    if v:
        return v
    if not os.path.isfile(ENGINE):
        raise FileNotFoundError(f"VOICEVOX engine not found at {ENGINE}; set WEBCOMIC_VOICEVOX_ENGINE to run.exe")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([ENGINE, "--use_gpu"], cwd=os.path.dirname(ENGINE), creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(1.5)
        v = engine_version()
        if v:
            return v
    raise TimeoutError(f"VOICEVOX engine did not answer at {HOST} within {wait_s:.0f} s")


def speakers() -> list[dict]:
    """Every voice as {"character", "style", "id"}; `id` is what say() takes."""
    out = []
    for sp in _get("/speakers"):
        for st in sp["styles"]:
            out.append({"character": sp["name"], "style": st["name"], "id": st["id"]})
    return out


def find_voice(character: str, style: str = "ノーマル") -> int:
    """The style id for a character and style name (e.g. "四国めたん", "ツンツン")."""
    for v in speakers():
        if v["character"] == character and v["style"] == style:
            return v["id"]
    have = sorted({v["style"] for v in speakers() if v["character"] == character})
    raise KeyError(f"no voice {character}/{style}; styles for {character}: {have or 'character not found'}")


def say(text: str, voice: int, out_wav: str, speed: float = 1.0, pitch: float = 0.0,
        intonation: float = 1.0, volume: float = 1.0, pre_s: float | None = None,
        post_s: float | None = None) -> dict:
    """Render one Japanese line to `out_wav`. Returns {"path", "seconds", "voice"}.

    speed      1.0 = the voice's own pace (0.5-2.0)
    pitch      semitone-ish offset, 0 = unchanged (about -0.15 to 0.15 is usable)
    intonation 1.0 = normal; lower is flatter, higher is more animated
    pre_s/post_s  silence before and after the line (the engine's default if None)
    """
    plan = json.loads(_post("/audio_query", {"text": text, "speaker": voice}))
    plan.update(speedScale=speed, pitchScale=pitch, intonationScale=intonation, volumeScale=volume)
    if pre_s is not None:
        plan["prePhonemeLength"] = pre_s
    if post_s is not None:
        plan["postPhonemeLength"] = post_s
    wav = _post("/synthesis", {"speaker": voice}, json.dumps(plan).encode("utf-8"))
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    with open(out_wav, "wb") as f:
        f.write(wav)
    import wave
    with wave.open(out_wav) as w:
        secs = w.getnframes() / w.getframerate()
    return {"path": out_wav, "seconds": round(secs, 3), "voice": voice}


def credits(voice_ids) -> list[str]:
    """The `VOICEVOX:<character>` credit lines for the voices a video used, one per character."""
    by_id = {v["id"]: v["character"] for v in speakers()}
    seen = []
    for i in voice_ids:
        c = by_id[i]
        if c not in seen:
            seen.append(c)
    return [f"VOICEVOX:{c}" for c in seen]
