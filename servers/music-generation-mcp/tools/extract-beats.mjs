/**
 * extract-beats.mjs — offline beat/onset analysis.
 *
 * Emits a beat grid + energy envelope so the EDIT can land on the music:
 * cuts snap to beats, flashes fire on downbeats, motion rides the envelope.
 *
 * Dependency-free by design: decodes with ffmpeg, then does spectral-flux onset
 * detection and tempo estimation in plain JS. No Python, no librosa, no extra
 * npm packages.
 *
 * ── DUPLICATE ────────────────────────────────────────────────────────────────
 * This is a second copy of anime-production-skill/assets/tools/extract-beats.mjs,
 * kept deliberately (ARCHITECTURE.md §7a asked for the beat tool to live with
 * music generation; the video pipeline still needs its own copy to stay
 * independently installable). The analysis code below is IDENTICAL — fix a bug
 * in one, port it to the other.
 *
 * The ONE divergence: an explicit `--ffmpeg <path>` flag. The skill's copy finds
 * ffmpeg inside Remotion's bundled compositor package, which this server does
 * not have. Search order here: --ffmpeg, then $WEBCOMIC_MUSIC_FFMPEG, then
 * Remotion's package (harmless if absent), then a system `ffmpeg`.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Usage:
 *   node tools/extract-beats.mjs track.mp3 [--out beats.json]
 *                                          [--bpm 128]  (skip detection)
 *                                          [--ffmpeg C:\path\to\ffmpeg.exe]
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync, mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { tmpdir } from "node:os";

const SR = 22050;      // analysis sample rate
const HOP = 512;       // ~23ms per frame
const WIN = 1024;
const FRAME_RATE = SR / HOP; // analysis frames per second

// ---------- CLI ----------
const argv = process.argv.slice(2);
if (argv.length === 0 || argv[0].startsWith("--")) {
  console.error("usage: node tools/extract-beats.mjs <audio> [--out path] [--bpm N]");
  process.exit(1);
}
const input = resolve(argv[0]);
const arg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i === -1 ? fallback : argv[i + 1];
};
// Default to a .ts module: no bundler `resolveJsonModule` assumptions, works
// in any harness. Pass `--out something.json` for raw JSON instead.
const outPath = resolve(arg("--out", "src/data/beats.ts"));
const forcedBpm = arg("--bpm", null) ? Number(arg("--bpm", null)) : null;

// ---------- 1. decode to mono PCM via ffmpeg ----------
/** Explicit flag/env first, then Remotion's platform-specific compositor
 *  package (present only in the video pipeline), then a system install. */
function findFfmpeg() {
  const explicit = arg("--ffmpeg", null) ?? process.env.WEBCOMIC_MUSIC_FFMPEG ?? null;
  if (explicit) {
    if (!existsSync(explicit)) {
      console.error(`ffmpeg not found at "${explicit}"`);
      process.exit(1);
    }
    return explicit;
  }
  const pkgs = [
    `@remotion/compositor-${process.platform}-${process.arch}-msvc`,
    `@remotion/compositor-${process.platform}-${process.arch}-gnu`,
    `@remotion/compositor-${process.platform}-${process.arch}`,
  ];
  const exe = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";
  for (const p of pkgs) {
    const guess = resolve(process.cwd(), "node_modules", p, exe);
    if (existsSync(guess)) return guess;
  }
  return "ffmpeg"; // fall back to a system install
}

const ffmpeg = findFfmpeg();
const wavPath = resolve(tmpdir(), `beats-${Date.now()}.wav`);
console.log(`decoding ${input} …`);
try {
  execFileSync(
    ffmpeg,
    ["-y", "-i", input, "-ac", "1", "-ar", String(SR),
     "-c:a", "pcm_s16le", "-f", "wav", wavPath],
    { stdio: ["ignore", "ignore", "pipe"] }
  );
} catch (e) {
  console.error(`ffmpeg decode failed using "${ffmpeg}".`);
  console.error(String(e.stderr ?? e.message).split("\n").slice(-5).join("\n"));
  process.exit(1);
}

// ---------- 2. parse WAV (find the data chunk; header size varies) ----------
const buf = readFileSync(wavPath);
let pos = 12, dataOffset = 44, dataLength = buf.length - 44;
while (pos < buf.length - 8) {
  const id = buf.toString("ascii", pos, pos + 4);
  const size = buf.readUInt32LE(pos + 4);
  if (id === "data") { dataOffset = pos + 8; dataLength = size; break; }
  pos += 8 + size + (size % 2);
}
const n = Math.floor(dataLength / 2);
const x = new Float32Array(n);
for (let i = 0; i < n; i++) x[i] = buf.readInt16LE(dataOffset + i * 2) / 32768;
try { unlinkSync(wavPath); } catch {}
const duration = n / SR;
console.log(`  ${duration.toFixed(2)}s @ ${SR}Hz`);

// ---------- 3. spectral flux ----------
// in-place iterative radix-2 FFT
function fft(re, im) {
  const N = re.length;
  for (let i = 1, j = 0; i < N; i++) {
    let bit = N >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= N; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < N; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ur = re[i + k], ui = im[i + k];
        const vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci;
        const vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr;
        re[i + k] = ur + vr; im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi;
        const ncr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}

const nFrames = Math.max(1, Math.floor((n - WIN) / HOP));
const nBins = WIN / 2;
const hann = new Float32Array(WIN);
for (let i = 0; i < WIN; i++) hann[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (WIN - 1)));

const flux = new Float32Array(nFrames);
const rms = new Float32Array(nFrames);
let prevMag = new Float32Array(nBins);

for (let f = 0; f < nFrames; f++) {
  const off = f * HOP;
  const re = new Float32Array(WIN), im = new Float32Array(WIN);
  let sum = 0;
  for (let i = 0; i < WIN; i++) {
    const s = x[off + i];
    re[i] = s * hann[i];
    sum += s * s;
  }
  rms[f] = Math.sqrt(sum / WIN);
  fft(re, im);
  let fl = 0;
  const mag = new Float32Array(nBins);
  for (let b = 0; b < nBins; b++) {
    mag[b] = Math.hypot(re[b], im[b]);
    const d = mag[b] - prevMag[b];
    if (d > 0) fl += d;           // half-wave rectified: onsets only
  }
  flux[f] = fl;
  prevMag = mag;
}

// normalise flux 0..1
let fmax = 0;
for (const v of flux) if (v > fmax) fmax = v;
if (fmax > 0) for (let i = 0; i < nFrames; i++) flux[i] /= fmax;

// ---------- 4. onset peak picking (adaptive threshold) ----------
const W = 12; // ~0.28s median window
const onsets = [];
for (let i = 1; i < nFrames - 1; i++) {
  let sum = 0, c = 0;
  for (let k = Math.max(0, i - W); k < Math.min(nFrames, i + W); k++) { sum += flux[k]; c++; }
  const thresh = sum / c + 0.08;
  if (flux[i] > thresh && flux[i] >= flux[i - 1] && flux[i] > flux[i + 1]) {
    const t = i / FRAME_RATE;
    if (onsets.length === 0 || t - onsets[onsets.length - 1] > 0.09) onsets.push(t);
  }
}

// ---------- 5. tempo: autocorrelate the flux over plausible BPM ----------
let bpm = forcedBpm;
if (!bpm) {
  let best = 0, bestScore = -1;
  for (let cand = 60; cand <= 190; cand += 0.25) {
    const lag = (60 / cand) * FRAME_RATE;
    let score = 0;
    for (let i = 0; i + lag * 2 < nFrames; i++) {
      const j = Math.round(i + lag), k = Math.round(i + lag * 2);
      score += flux[i] * flux[j] * flux[k];   // reward 3-in-a-row periodicity
    }
    score /= Math.max(1, nFrames - lag * 2);
    if (score > bestScore) { bestScore = score; best = cand; }
  }
  bpm = best;
  // fold absurdly fast tempi back into a musical range
  while (bpm > 170) bpm /= 2;
  while (bpm < 70) bpm *= 2;
}
const period = 60 / bpm;

// ---------- 6. phase: slide the grid to best fit detected onsets ----------
let bestOffset = 0, bestHits = -1;
for (let o = 0; o < period; o += 0.005) {
  let hits = 0;
  for (const t of onsets) {
    const d = Math.abs(((t - o) % period + period) % period);
    const dist = Math.min(d, period - d);
    if (dist < 0.06) hits++;
  }
  if (hits > bestHits) { bestHits = hits; bestOffset = o; }
}

const beats = [];
for (let t = bestOffset; t < duration; t += period) beats.push(Number(t.toFixed(4)));
const downbeats = beats.filter((_, i) => i % 4 === 0);

// ---------- 7. energy envelope, one value per beat-ish slice ----------
const ENV_HZ = 30; // one sample per video frame at 30fps
const envLen = Math.floor(duration * ENV_HZ);
const envelope = new Array(envLen);
let rmax = 0;
for (const v of rms) if (v > rmax) rmax = v;
for (let i = 0; i < envLen; i++) {
  const f = Math.min(nFrames - 1, Math.floor((i / ENV_HZ) * FRAME_RATE));
  envelope[i] = Number((rmax > 0 ? rms[f] / rmax : 0).toFixed(3));
}

const out = {
  source: input.replace(/\\/g, "/").split("/").pop(),
  duration: Number(duration.toFixed(3)),
  bpm: Number(bpm.toFixed(2)),
  offset: Number(bestOffset.toFixed(4)),
  beatInterval: Number(period.toFixed(4)),
  beats,
  downbeats,
  onsets: onsets.map((t) => Number(t.toFixed(3))),
  envelope,
  envelopeRate: ENV_HZ,
};

mkdirSync(dirname(outPath), { recursive: true });
if (outPath.endsWith(".ts")) {
  writeFileSync(outPath, `// GENERATED by tools/extract-beats.mjs — do not edit by hand.
// Source: ${out.source}   ${out.bpm} BPM   bar = ${(out.beatInterval * 4).toFixed(3)}s
export interface BeatMap {
  source: string; duration: number; bpm: number; offset: number;
  beatInterval: number; beats: number[]; downbeats: number[];
  onsets: number[]; envelope: number[]; envelopeRate: number;
}

export const beatMap: BeatMap = ${JSON.stringify(out)};
`);
} else {
  writeFileSync(outPath, JSON.stringify(out, null, 2));
}
console.log(`  BPM ${out.bpm}  offset ${out.offset}s  ${beats.length} beats, ${onsets.length} onsets`);
console.log(`wrote ${outPath}`);
