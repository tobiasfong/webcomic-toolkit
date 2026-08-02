// PLACEHOLDER — replace by running:
//   node tools/extract-beats.mjs public/bgm/<your-song>.mp3
// which overwrites this file with the real beat map for your track.
//
// With these neutral values the engine still renders: `envelopeAt` returns 0
// and `downbeatDecay` returns 0, so audio-reactive bloom and downbeat flashes
// are simply inert until a real beat map exists. Keep `beatSync.enabled: false`
// in manhwa-panels.ts until then.
export interface BeatMap {
  source: string; duration: number; bpm: number; offset: number;
  beatInterval: number; beats: number[]; downbeats: number[];
  onsets: number[]; envelope: number[]; envelopeRate: number;
}

export const beatMap: BeatMap = {
  source: "(none)",
  duration: 0,
  bpm: 120,
  offset: 0,
  beatInterval: 0.5, // 120 BPM → bar = 2.0s
  beats: [],
  downbeats: [],
  onsets: [],
  envelope: [],
  envelopeRate: 30,
};
