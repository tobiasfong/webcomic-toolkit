import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { beatMap } from "../data/beats";

/**
 * 仕上げ（グレード）/ Post-processing stack — the "anime look".
 *
 * Most of what separates an anime teaser from a slideshow is the grade, not the
 * motion: halation on highlights, grain, a vignette, and impact flashes that
 * land on the music. All of it is applied to the composited frame, so it costs
 * one pass regardless of how many panels are underneath.
 *
 * Bloom uses `backdrop-filter`, which samples what is already painted below —
 * so the panels (including video) are never rendered twice.
 */
export interface GradeConfig {
  /** ハレーション/ブルーム 0–1。省略時 0.35 */
  bloom?: number;
  /** フィルムグレイン 0–1。省略時 0.12 */
  grain?: number;
  /** 周辺減光 0–1。省略時 0.35 */
  vignette?: number;
  /** ダウンビートの白フラッシュ 0–1。省略時 0.18（0で無効） */
  flash?: number;
  /** ダウンビートのズームパンチ（拡大率）。省略時 0.012（0で無効） */
  punch?: number;
  /** 音量に反応してブルームを強める量 0–1。省略時 0.5 */
  audioReactive?: number;
  /** 全体の彩度。省略時 1.06 */
  saturation?: number;
  /** 全体のコントラスト。省略時 1.04 */
  contrast?: number;
}

/** 音量エンベロープ（0–1）をフレーム番号から引く */
export const envelopeAt = (frame: number, fps: number): number => {
  const i = Math.floor((frame / fps) * beatMap.envelopeRate);
  return beatMap.envelope[Math.max(0, Math.min(beatMap.envelope.length - 1, i))] ?? 0;
};

/**
 * 直前のダウンビートからの減衰（1→0）。フラッシュ・パンチ用。
 * decay: 効果が消えるまでの秒数
 */
export const downbeatDecay = (frame: number, fps: number, decay = 0.18): number => {
  const t = frame / fps;
  let last = -Infinity;
  for (const d of beatMap.downbeats) {
    if (d <= t) last = d;
    else break;
  }
  if (!isFinite(last)) return 0;
  const dt = t - last;
  if (dt > decay) return 0;
  return Math.pow(1 - dt / decay, 2); // ease-out
};

export const Grade: React.FC<{
  config?: GradeConfig;
  /**
   * 0–1。ショーケース（白背景の表紙）など、グレードを効かせたくない場面で 1 に。
   * 周辺減光・グレイン・ブルームが抑制され、印刷広告のような清潔な白が保てます。
   */
  damp?: number;
  children: React.ReactNode;
}> = ({ config = {}, damp = 0, children }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  const k = 1 - Math.max(0, Math.min(1, damp));
  const bloom = (config.bloom ?? 0.35) * k;
  const grain = (config.grain ?? 0.12) * (0.25 + 0.75 * k); // 粒子は少しだけ残す
  const vignette = (config.vignette ?? 0.35) * k;
  const flash = (config.flash ?? 0.18) * k;
  const punch = config.punch ?? 0.012;
  const reactive = config.audioReactive ?? 0.5;
  const saturation = config.saturation ?? 1.06;
  const contrast = config.contrast ?? 1.04;

  const env = envelopeAt(frame, fps);
  const hit = downbeatDecay(frame, fps);

  // 音が大きいほどブルームが強い / louder music = stronger halation
  const bloomNow = bloom * (1 + reactive * (env - 0.5));
  const scale = 1 + punch * hit;

  // グレインは1枚のテクスチャを毎フレーム動かす（フィルタ再計算を避ける）
  const grainSeed = frame % 12;
  const gx = ((grainSeed * 37) % 11) - 5;
  const gy = ((grainSeed * 53) % 11) - 5;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* 本体（ダウンビートで微妙に拡大） */}
      <AbsoluteFill
        style={{
          transform: `scale(${scale})`,
          filter: `saturate(${saturation}) contrast(${contrast})`,
          willChange: "transform",
        }}
      >
        {children}
      </AbsoluteFill>

      {/* ブルーム / halation — backdrop-filter so children aren't re-rendered.
          高コントラストで暗部を黒に潰してから screen 合成するのが要点：
          brightness だけだと画面全体が白っぽく濁る（ハイライトだけを光らせる）。 */}
      {bloomNow > 0.01 && (
        <AbsoluteFill
          style={{
            backdropFilter: `blur(${16 + 8 * env}px) contrast(2.6) brightness(1.15) saturate(1.15)`,
            WebkitBackdropFilter: `blur(${16 + 8 * env}px) contrast(2.6) brightness(1.15)`,
            mixBlendMode: "screen",
            opacity: Math.max(0, Math.min(0.6, bloomNow)),
            pointerEvents: "none",
          }}
        />
      )}

      {/* フィルムグレイン */}
      {grain > 0.001 && (
        <AbsoluteFill
          style={{
            mixBlendMode: "overlay",
            opacity: grain,
            pointerEvents: "none",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: -20,
              top: -20,
              width: width + 40,
              height: height + 40,
              transform: `translate(${gx}px, ${gy}px)`,
              backgroundImage:
                "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/></filter><rect width='180' height='180' filter='url(%23n)' opacity='0.9'/></svg>\")",
              backgroundRepeat: "repeat",
            }}
          />
        </AbsoluteFill>
      )}

      {/* 周辺減光 */}
      {vignette > 0.001 && (
        <AbsoluteFill
          style={{
            background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,${vignette}) 100%)`,
            pointerEvents: "none",
          }}
        />
      )}

      {/* インパクトの白フラッシュ（ダウンビート） */}
      {flash > 0.001 && hit > 0 && (
        <AbsoluteFill
          style={{
            backgroundColor: "#fff",
            opacity: flash * hit,
            mixBlendMode: "screen",
            pointerEvents: "none",
          }}
        />
      )}
    </AbsoluteFill>
  );
};

/** 開幕/終幕の黒フェード */
export const FadeInOut: React.FC<{ totalFrames: number; seconds?: number }> = ({
  totalFrames,
  seconds = 0.5,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const f = seconds * fps;
  const o = Math.max(
    interpolate(frame, [0, f], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
    interpolate(frame, [totalFrames - f, totalFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );
  if (o <= 0.001) return null;
  return <AbsoluteFill style={{ backgroundColor: "#000", opacity: o, pointerEvents: "none" }} />;
};
