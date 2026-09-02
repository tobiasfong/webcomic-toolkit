"""Synthesize the battle sound effects, the way fx_plates.py draws the visuals.

    python sfx_plates.py <path-to-game-dir>

WHY SYNTHESIZED RATHER THAN GENERATED OR SOURCED
------------------------------------------------
The same argument that put the impact plates in a script instead of a
diffusion model. These sounds are SHORT, ABSTRACT and EXACTLY SPECIFIED --
a crack at a known moment, a shimmer of a known length, a swish that has to
sit under a 70 ms flash. That is a description of arithmetic, not of a
performance.

The music server is not the tool for it either: ACE-Step writes songs, with
a structure, a tempo and a vocal. Asking it for a half-second sword swish is
asking a band for a door slam.

Synthesized, they are deterministic (fixed seeds, so a rerun is identical),
tunable by one number, free of VRAM and licensing, and consistent across every
fight in the series -- and they can be recolored per magic system the same way
the plates are, by moving a filter rather than by finding another recording.

⚠ EVERY SOUND IS MATCHED TO THE PLATE IT PLAYS UNDER. The visual timings are
not decoration: an impact plate is 50 ms in, 60 ms held, 400 ms out, so an
impact SOUND whose attack lands 200 ms late plays against an empty screen.
Attack times here are all under 15 ms for that reason, and the tails are what
carry the length.

⚠ MONO, 44.1 kHz. Stereo would cost double the download for effects that are
centered anyway, and the web build fetches audio on demand -- their size is
wait time before an impact, exactly as it is for the plates.
"""
import math
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

SR = 44100
OUT = out_dir(game_dir(), "audio", "sfx")


# ---------------------------------------------------------------- helpers

def t(seconds):
    return np.arange(int(SR * seconds)) / float(SR)


def noise(seconds, seed):
    """White noise. Seeded, so a rerun produces a byte-identical file."""
    return noise_n(int(SR * seconds), seed)


def noise_n(n, seed):
    """White noise of EXACTLY n samples.

    ⚠ Use this wherever the length has to line up with something else.
    Going through seconds and back -- noise(gl / SR) -- loses a sample to
    float rounding, and the grain then fails to add to an envelope of length
    gl with a broadcast error. Cheap to hit, trivial to avoid, invisible
    until it throws.
    """
    return np.random.default_rng(seed).uniform(-1.0, 1.0, n)


def lowpass(x, cutoff):
    """One-pole lowpass. Cheap, and its gentle slope is the point: a steep
    filter on noise sounds synthetic, where a soft one sounds like air."""
    a = math.exp(-2.0 * math.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def highpass(x, cutoff):
    return x - lowpass(x, cutoff)


def env(n, attack, decay, curve=2.5):
    """Percussive envelope: near-instant attack, power-curve decay.

    The curve matters more than the length. A linear fade reads as a
    synthesizer; a power curve reads as something that was struck.
    """
    a = max(1, int(SR * attack))
    d = max(1, n - a)
    return np.concatenate([
        np.linspace(0.0, 1.0, a),
        (1.0 - np.linspace(0.0, 1.0, d)) ** curve,
    ])[:n]


def sweep(dur, f0, f1, curve=1.0):
    """A sine whose pitch glides. Phase is integrated rather than computed
    per-sample, because sin(2*pi*f(t)*t) glides at the WRONG rate -- a
    mistake that sounds close enough to be believed."""
    tt = t(dur)
    k = (tt / tt[-1]) ** curve
    f = f0 + (f1 - f0) * k
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def norm(x, peak=0.89):
    m = np.max(np.abs(x))
    return x * (peak / m) if m > 0 else x


def save(name, x):
    x = norm(x)
    # 3 ms of fade at each end. Without it the first and last sample are a
    # step, and a step is a click -- audible on every single play.
    f = int(SR * 0.003)
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    data = (np.clip(x, -1, 1) * 32767).astype("<i2")
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    print("%-16s %5.2f s  %6.0f KB  %s"
          % (name, len(x) / float(SR), os.path.getsize(path) / 1024.0, path))


# ---------------------------------------------------------------- sounds

def sword_swish(seed=3):
    """A blade cutting air, for a form performed rather than swung.

    Air, not metal. The swordsman is performing a form in the open -- nothing
    is struck,
    so there is no impact and no ring. The whole sound is a band of noise
    swept upward and back down, which is what a blade passing the ear
    actually is: the pitch rises as it approaches and falls as it leaves.
    """
    d = 0.30
    n = int(SR * d)
    body = highpass(lowpass(noise(d, seed), 5200), 700)
    # The doppler-ish arc: brightest in the middle of the stroke.
    arc = np.sin(np.linspace(0, np.pi, n)) ** 1.4
    return body[:n] * arc * env(n, 0.012, d, curve=1.4)


def sword_ring(seed=9):
    """Metal answering metal, kept for a clash rather than a swing."""
    d = 0.9
    n = int(SR * d)
    out = np.zeros(n)
    # Inharmonic partials: a struck blade is not a harmonic series, and
    # tuning these to one would make it a bell.
    for f, amp, dec in ((2180, 1.0, 0.42), (3310, 0.62, 0.30),
                        (4790, 0.40, 0.22), (6620, 0.24, 0.15)):
        e = np.exp(-np.arange(n) / (SR * dec))
        out += amp * np.sin(2 * np.pi * f * t(d)) * e
    strike = highpass(noise(0.02, seed), 2500) * env(int(SR * 0.02), 0.001, 0.02)
    out[:len(strike)] += strike * 2.2
    return out * env(n, 0.001, d, curve=1.1)


def ice_freeze(seed=17):
    """Water becoming ice: a crystalline crackle over a rising hiss.

    Two layers, and both are needed. The hiss swept UPWARD is the growth --
    something spreading and tightening. The grains are the crystals forming,
    scattered rather than regular, because a regular pulse train reads as a
    machine.
    """
    d = 0.85
    n = int(SR * d)
    hiss = highpass(noise(d, seed), 1800)[:n]
    hiss *= np.linspace(0.25, 1.0, n) ** 1.6
    hiss *= env(n, 0.02, d, curve=1.3) * 0.55

    rng = np.random.default_rng(seed + 1)
    grains = np.zeros(n)
    for _ in range(90):
        at = int(rng.uniform(0, 0.82) * n)
        gl = int(SR * rng.uniform(0.004, 0.018))
        if at + gl >= n:
            continue
        g = highpass(noise_n(gl, int(rng.integers(1, 10 ** 6))), 4000)
        grains[at:at + gl] += g[:gl] * env(gl, 0.0005, gl / SR, curve=3.0) \
            * rng.uniform(0.3, 1.0)
    return hiss + grains * 0.8


def ice_shatter(seed=23):
    """An ice barrier breaking: many small fragments, front-loaded.

    Distinct from the freeze by DIRECTION. Freezing accumulates, so its
    density rises; shattering disperses, so density falls away from a hard
    front. Same grain material, opposite envelope -- which is most of what
    tells a listener which one they heard.
    """
    d = 1.0
    n = int(SR * d)
    out = np.zeros(n)
    crack = highpass(noise(0.05, seed), 1200)
    out[:len(crack)] += crack * env(len(crack), 0.0008, 0.05, curve=2.0) * 1.6

    rng = np.random.default_rng(seed + 5)
    for _ in range(150):
        at = int((rng.uniform(0, 1) ** 2.1) * 0.9 * n)   # clustered at the front
        gl = int(SR * rng.uniform(0.005, 0.030))
        if at + gl >= n:
            continue
        g = highpass(noise_n(gl, int(rng.integers(1, 10 ** 6))), 3000)
        out[at:at + gl] += g[:gl] * env(gl, 0.0005, gl / SR, curve=2.6) \
            * rng.uniform(0.15, 0.9)
    return out * env(n, 0.001, d, curve=1.5)


def thunder(seed=31):
    """A rival's lightning sword art.

    A CRACK and a BODY, in that order and overlapping. The crack is what
    arrives with the plate -- bright, 40 ms, gone. The body is the low
    rumble underneath it, and it is what makes the crack read as thunder
    rather than as static.

    The rumble is lowpassed hard and given a slow decay; real thunder is long
    because the sound arrives from a stroke kilometres long, and shortening it
    to fit a flash is what makes synthetic thunder sound like a balloon.
    """
    d = 1.4
    n = int(SR * d)
    crack = highpass(noise(0.06, seed), 2200)
    body = lowpass(noise(d, seed + 2), 220)[:n]
    body *= env(n, 0.006, d, curve=1.8) * 0.9
    # A little mid-band so it is not pure mud on small speakers.
    mid = lowpass(highpass(noise(d, seed + 3), 300), 1400)[:n]
    mid *= env(n, 0.004, 0.55, curve=2.4) * 0.35
    out = body + mid
    out[:len(crack)] += crack * env(len(crack), 0.0006, 0.06, curve=2.2) * 1.5
    return out


def frost_bloom(seed=41):
    """The conjured ice ornament: a shimmer, not a hit.

    The only sound here with a SLOW attack, because it is the only beat where
    nothing is struck -- he raises a hand and grows something. High partials
    with a gentle rise, a whisper of air under them, and no transient at all.
    Give this one a transient and it becomes an attack.
    """
    d = 1.1
    n = int(SR * d)
    out = np.zeros(n)
    for f, amp in ((3140, 1.0), (4190, 0.55), (5280, 0.38), (7010, 0.22)):
        det = 1.0 + 0.0016 * math.sin(f)      # fixed, tiny detune per partial
        out += amp * np.sin(2 * np.pi * f * det * t(d))
    rise = np.linspace(0, 1, n) ** 0.7
    fall = np.concatenate([np.ones(int(n * 0.45)),
                           np.linspace(1, 0, n - int(n * 0.45)) ** 2.0])
    out *= rise * fall * 0.5
    air = highpass(noise(d, seed), 6000)[:n] * rise * fall * 0.25
    return out + air


def dark_arc(seed=53):
    """The yin sword technique: a dark arc, and it must not glitter.

    Every other attack here lives in the high band -- crystal, metal, the
    crack of lightning. This one is deliberately the opposite: the noise is
    lowpassed hard and swept DOWNWARD, so it reads as something opening
    rather than something striking. Brightness would make it another sword.

    The technique's plate is a void with a colored rim, and this is the same
    idea in sound: a hole, edged.
    """
    d = 0.75
    n = int(SR * d)
    body = lowpass(noise(d, seed), 900)[:n]
    body *= env(n, 0.008, d, curve=1.6)
    # A downward sweep gives the arc its direction of travel.
    edge = sweep(d, 520, 90, curve=0.6) * np.exp(-np.arange(n) / (SR * 0.30))
    sub = np.sin(2 * np.pi * 52 * t(d)) * np.exp(-np.arange(n) / (SR * 0.22))
    return body * 1.0 + edge * 0.35 + sub * 0.5


def shuriken(seed=61):
    """A thrown star: a thin whistle that arrives and stops.

    Short, narrow-band and rising. It stops rather than decaying, because the
    star lands -- a tail would say it sailed past.
    """
    d = 0.34
    n = int(SR * d)
    whistle = sweep(d, 1450, 3300, curve=1.5)
    body = whistle * np.linspace(0.35, 1.0, n) ** 1.2
    air = highpass(noise(d, seed), 3500)[:n] * 0.35
    out = (body * 0.8 + air) * env(n, 0.010, d, curve=3.2)
    return out


def breeze(seed=71):
    """Evade: a breath of wind where a blow should have been.

    The odd one out in this set, and deliberately so. Every other sound here
    is something happening; this one is something NOT happening -- the blade
    passes, nothing connects, and the only trace is moving air.

    So it has no transient at all and no high end to speak of: a soft band of
    noise that swells and falls. Two slow amplitude waves at different rates
    keep it from sounding like a fade on a noise generator, which is what a
    single envelope over white noise always sounds like.
    """
    d = 1.0
    n = int(SR * d)
    air = lowpass(highpass(noise(d, seed), 260), 1500)[:n]
    swell = np.sin(np.linspace(0, np.pi, n)) ** 1.3
    gust = 0.75 + 0.25 * np.sin(np.linspace(0, 2.7 * np.pi, n) + 0.6)
    return air * swell * gust * 0.9


def qi_slash(seed=83):
    """A master's blade of light. Not a sword sound.

    He is not swinging steel, he is releasing pressure, so
    this is deliberately built the opposite way from sword_ring: a low tonal
    core with air over it, rather than metal partials. Metal here would make
    him a swordsman, and the whole point of the scene is that he is not
    fighting the protagonist so much as demonstrating a difference in kind.
    """
    d = 0.7
    n = int(SR * d)
    core = sweep(d, 220, 70, curve=0.7) * np.exp(-np.arange(n) / (SR * 0.26))
    air = highpass(lowpass(noise(d, seed), 3800), 500)[:n]
    air *= env(n, 0.006, d, curve=1.7)
    return core * 0.8 + air * 0.9


def qi_burst(seed=89):
    """Raw pressure arriving -- his ki filling a room.

    A swell rather than a hit. The attack is fast but not instant and the
    body is low and wide, because what the scene describes is weight, not
    impact: it presses on people rather than striking them.
    """
    d = 1.2
    n = int(SR * d)
    body = lowpass(noise(d, seed), 320)[:n] * env(n, 0.035, d, curve=1.5)
    swell = np.sin(np.linspace(0, np.pi, n)) ** 0.9
    sub = np.sin(2 * np.pi * 44 * t(d)) * np.exp(-np.arange(n) / (SR * 0.4))
    return body * swell * 1.1 + sub * 0.55


def blast_boom(seed=97):
    """The yin technique's shockwave: concussive, and brighter than qi.

    Told apart from qi_burst by its TRANSIENT. Pressure swells; a shockwave
    starts at full and collapses. Same low body, opposite front.
    """
    d = 1.1
    n = int(SR * d)
    body = lowpass(noise(d, seed), 420)[:n] * env(n, 0.002, d, curve=2.2)
    crack = highpass(noise(0.04, seed + 1), 1500)
    out = body * 1.0
    out[:len(crack)] += crack * env(len(crack), 0.0005, 0.04, curve=2.0) * 1.1
    sub = np.sin(2 * np.pi * 38 * t(d)) * np.exp(-np.arange(n) / (SR * 0.30))
    return out + sub * 0.6


def ward_hum(seed=101):
    """The defensive array coming up -- a drone, not a strike.

    Held tones that rise and settle, because a ward is a thing that STAYS.
    Tuned to a fifth: it has to read as deliberate and constructed, which is
    what the drawn magic circle looks like, and a dissonant interval would
    make it ominous instead.
    """
    d = 1.5
    n = int(SR * d)
    out = np.zeros(n)
    for f, amp in ((196.0, 1.0), (294.0, 0.7), (392.0, 0.45), (588.0, 0.22)):
        out += amp * np.sin(2 * np.pi * f * t(d))
    rise = np.clip(np.linspace(0, 2.4, n), 0, 1) ** 0.8
    fall = np.concatenate([np.ones(int(n * 0.55)),
                           np.linspace(1, 0, n - int(n * 0.55)) ** 1.6])
    shimmer = highpass(noise(d, seed), 5000)[:n] * 0.18
    return (out * 0.32 + shimmer) * rise * fall


def sword_shimmer(seed=103):
    """A blade catching light -- the repaired sword, not a swing.

    Bell-like and gentle, with a slow attack so it cannot be mistaken for an
    impact. This plays while a sword is being LOOKED at.
    """
    d = 1.3
    n = int(SR * d)
    out = np.zeros(n)
    for f, amp, dec in ((1760, 1.0, 0.75), (2640, 0.5, 0.55),
                        (3520, 0.32, 0.40), (5280, 0.16, 0.28)):
        out += amp * np.sin(2 * np.pi * f * t(d)) * np.exp(-np.arange(n) / (SR * dec))
    attack = np.clip(np.linspace(0, 6, n), 0, 1) ** 1.2
    return out * attack * 0.5


def token_ting(seed=107):
    """A small metal token tossed across a room.

    Short and high, and quiet by design -- it crosses a conversation rather
    than interrupting one, which is exactly why its plate is additive instead
    of blacking out the hall.
    """
    d = 0.55
    n = int(SR * d)
    out = np.zeros(n)
    for f, amp, dec in ((3520, 1.0, 0.22), (5270, 0.45, 0.14), (7040, 0.2, 0.09)):
        out += amp * np.sin(2 * np.pi * f * t(d)) * np.exp(-np.arange(n) / (SR * dec))
    return out * 0.55


def blizzard_gust(seed=109):
    """The world turning to tundra in one breath.

    The harsh sibling of breeze(). Same idea -- moving air -- but this one has
    a front, far more high band, and it does not settle. It plays once, at the
    transformation; the falling snow that follows is a picture, not a sound.
    """
    d = 2.2
    n = int(SR * d)
    air = highpass(noise(d, seed), 700)[:n]
    body = lowpass(noise(d, seed + 1), 900)[:n]
    swell = np.clip(np.linspace(0, 3.5, n), 0, 1) ** 0.5
    fall = np.concatenate([np.ones(int(n * 0.35)),
                           np.linspace(1, 0, n - int(n * 0.35)) ** 1.4])
    gust = 0.7 + 0.3 * np.sin(np.linspace(0, 5.1 * np.pi, n))
    return (air * 0.75 + body * 0.6) * swell * fall * gust


SOUNDS = {
    "sfx_sword_swish": sword_swish,
    "sfx_sword_ring": sword_ring,
    "sfx_ice_freeze": ice_freeze,
    "sfx_ice_shatter": ice_shatter,
    "sfx_thunder": thunder,
    "sfx_frost_bloom": frost_bloom,
    "sfx_dark_arc": dark_arc,
    "sfx_shuriken": shuriken,
    "sfx_breeze": breeze,
    "sfx_qi_slash": qi_slash,
    "sfx_qi_burst": qi_burst,
    "sfx_blast_boom": blast_boom,
    "sfx_ward_hum": ward_hum,
    "sfx_sword_shimmer": sword_shimmer,
    "sfx_token_ting": token_ting,
    "sfx_blizzard_gust": blizzard_gust,
}

if __name__ == "__main__":
    for name, fn in SOUNDS.items():
        save(name, fn())
