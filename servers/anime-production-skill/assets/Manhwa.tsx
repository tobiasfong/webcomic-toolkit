import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";
import {
  panels,
  bgm,
  FPS,
  TRANSITION_FRAMES,
  BACKGROUND_COLOR,
  beatSync,
  grade,
  type Panel,
  type TextOverlay,
  type OverlayPosition,
} from "./data/manhwa-panels";
import { Effects } from "./effects/Effects";
import { DepthScene } from "./effects/DepthScene";
import { Grade, FadeInOut, envelopeAt } from "./effects/Grade";
import { beatMap } from "./data/beats";

// 日本語対応フォント（オーバーレイ文字用）/ Japanese-capable font for overlays
const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
  ignoreTooManyRequestsWarning: true,
});

const T = TRANSITION_FRAMES;

// 動画クリップ（Kling/Pika等）か静止画かを拡張子で判定 / video clip vs still image
const isVideo = (src: string) => /\.(mp4|webm|mov|m4v)$/i.test(src);

/** 1小節の秒数 / seconds per bar (4 beats) */
const barSeconds = beatMap.beatInterval * 4;

// パネルのメディア（静止画 or 動画）。動画は音声をミュート（BGM優先）
const Media: React.FC<{
  src: string;
  video: boolean;
  style: React.CSSProperties;
  /** 再生速度（クリップ尺をパネル尺に合わせる） */
  playbackRate?: number;
}> = ({ src, video, style, playbackRate }) =>
  video ? (
    <OffthreadVideo src={src} style={style} muted playbackRate={playbackRate} />
  ) : (
    <Img src={src} style={style} />
  );

// テキストの水平寄せ / horizontal alignment within a row
const hJustify = (pos: OverlayPosition): React.CSSProperties["justifyContent"] =>
  pos.endsWith("center") ? "center" : pos.endsWith("right") ? "flex-end" : "flex-start";

const OverlayText: React.FC<{ o: TextOverlay }> = ({ o }) => (
  <div style={{ display: "flex", justifyContent: hJustify(o.position ?? "bottom-left") }}>
    <div
      style={{
        color: o.color ?? (o.plain ? "#1a1a1a" : "#ffffff"),
        fontSize: o.fontSize ?? 26,
        fontFamily,
        fontWeight: 700,
        lineHeight: 1.4,
        whiteSpace: "pre-line",
        textAlign: (o.position ?? "bottom-left").endsWith("center")
          ? "center"
          : (o.position ?? "bottom-left").endsWith("right")
            ? "right"
            : "left",
        background: o.plain ? "transparent" : "rgba(0,0,0,0.6)",
        padding: o.plain ? 0 : "10px 18px",
        borderRadius: o.plain ? 0 : 10,
        textShadow: o.plain ? undefined : "0 2px 6px rgba(0,0,0,0.9)",
      }}
    >
      {o.text}
    </div>
  </div>
);

// 画像周りの黒帯に表示するテキスト群（同じ辺のテキストは縦に積む）
const Overlays: React.FC<{ overlays?: TextOverlay[] }> = ({ overlays }) => {
  const frame = useCurrentFrame();
  if (!overlays || overlays.length === 0) return null;
  const appear = interpolate(frame, [6, 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const top = overlays.filter((o) => (o.position ?? "bottom-left").startsWith("top"));
  const bottom = overlays.filter((o) => !(o.position ?? "bottom-left").startsWith("top"));
  const column = (items: TextOverlay[], edge: "top" | "bottom"): React.CSSProperties => ({
    display: "flex",
    flexDirection: "column",
    gap: 10,
    padding: 40,
    justifyContent: edge === "top" ? "flex-start" : "flex-end",
    opacity: appear,
    pointerEvents: "none",
  });
  return (
    <>
      {top.length > 0 && (
        <AbsoluteFill style={column(top, "top")}>
          {top.map((o, i) => (
            <OverlayText key={i} o={o} />
          ))}
        </AbsoluteFill>
      )}
      {bottom.length > 0 && (
        <AbsoluteFill style={column(bottom, "bottom")}>
          {bottom.map((o, i) => (
            <OverlayText key={i} o={o} />
          ))}
        </AbsoluteFill>
      )}
    </>
  );
};

/**
 * 各パネルのタイミングを計算 / Compute panel timings.
 *
 * ビート同期時は、各カット時刻を拍のグリッド上に置き、ディゾルブが
 * 「拍の頭で完了する」ように T フレーム手前から重ねます（拍をまたがない）。
 * 前のパネルはフェードアウトさせず、新しいパネルが上に乗って消す方式なので
 * クロスフェード中に暗く沈みません。
 */
export const getPanelTimings = () => {
  const synced = beatSync.enabled && panels.some((p) => p.bars);

  // カット時刻（秒）: cuts[i] = パネル i が完全に現れる時刻
  const cuts: number[] = [0];
  if (synced) {
    let bars = 0;
    for (const p of panels) {
      bars += p.bars ?? p.durationInSeconds / barSeconds;
      // 最初のカット以外は拍グリッド（offset + n小節）に正確に乗せる
      cuts.push(beatMap.offset + bars * barSeconds);
    }
  } else {
    let t = 0;
    for (const p of panels) {
      t += p.durationInSeconds;
      cuts.push(t);
    }
  }

  const cutFrames = cuts.map((t) => Math.round(t * FPS));
  const timings = panels.map((_, i) => {
    const start = i === 0 ? 0 : Math.max(0, cutFrames[i] - T);
    return {
      start,
      frames: Math.max(1, cutFrames[i + 1] - start),
      /** フェードイン完了までのフレーム数（0 = 即座に表示） */
      fadeIn: i === 0 ? 0 : cutFrames[i] - start,
      /** このパネルが実際に見えている秒数（動画の再生速度計算用） */
      seconds: (cutFrames[i + 1] - start) / FPS,
    };
  });

  const totalFrames = timings.length
    ? timings[timings.length - 1].start + timings[timings.length - 1].frames
    : FPS;
  return { timings, totalFrames };
};

export const MANHWA_DURATION = getPanelTimings().totalFrames;

// ケンバーンズ効果（ゆっくりしたパン/ズーム）の transform を返す
const kenBurns = (motion: Panel["motion"], progress: number): string => {
  // progress: 0→1（パネル表示中の進行度）
  const zoomFrom = 1.06;
  const zoomTo = 1.2;
  const pan = 6; // パーセント移動量
  switch (motion) {
    case "zoomOut":
      return `scale(${interpolate(progress, [0, 1], [zoomTo, zoomFrom])})`;
    case "panUp":
      return `scale(${zoomTo}) translateY(${interpolate(progress, [0, 1], [pan, -pan])}%)`;
    case "panDown":
      return `scale(${zoomTo}) translateY(${interpolate(progress, [0, 1], [-pan, pan])}%)`;
    case "panLeft":
      return `scale(${zoomTo}) translateX(${interpolate(progress, [0, 1], [pan, -pan])}%)`;
    case "panRight":
      return `scale(${zoomTo}) translateX(${interpolate(progress, [0, 1], [-pan, pan])}%)`;
    case "zoomIn":
    default:
      return `scale(${interpolate(progress, [0, 1], [zoomFrom, zoomTo])})`;
  }
};

const PanelView: React.FC<{
  panel: Panel;
  frames: number;
  fadeIn: number;
  seconds: number;
}> = ({ panel, frames, fadeIn, seconds }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // 新しいパネルが上に重なって前を消すので、フェードアウトは不要
  // (fading the new panel in ON TOP avoids the mid-dissolve dip to black)
  const opacity =
    fadeIn <= 0
      ? 1
      : interpolate(frame, [0, fadeIn], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });

  const src = staticFile(panel.src);
  const video = isVideo(panel.src);
  // クリップ尺 ≠ パネル尺 なら再生速度でフィット（カメラワークの尻切れ防止）
  const playbackRate =
    video && panel.clipSeconds && seconds > 0
      ? Math.max(0.25, Math.min(4, panel.clipSeconds / seconds))
      : undefined;

  // ショーケース表示（角川ラノベ広告風）：単色背景 + 影付きの表紙 + 余白クレジット。静止。
  if (panel.showcase) {
    const sc = panel.showcase;
    const pos = sc.artPosition ?? "top";
    const size = (sc.artSize ?? 0.72) * 100;
    return (
      <AbsoluteFill style={{ opacity, backgroundColor: sc.background ?? "#ffffff" }}>
        <AbsoluteFill
          style={{
            flexDirection: pos === "left" ? "row" : pos === "right" ? "row-reverse" : "column",
            justifyContent: pos === "center" ? "center" : "flex-start",
            alignItems: "center",
            padding: 60,
          }}
        >
          <Media
            src={src}
            video={video}
            playbackRate={playbackRate}
            style={{
              maxWidth: pos === "left" || pos === "right" ? `${size}%` : "100%",
              maxHeight: pos === "left" || pos === "right" ? "100%" : `${size}%`,
              objectFit: "contain",
              boxShadow: "0 18px 50px rgba(0,0,0,0.28)",
            }}
          />
        </AbsoluteFill>
        <Effects effects={panel.effects} />
        <Overlays overlays={panel.overlays} />
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ opacity }}>
      {/* ぼかし背景（縦横比が合わない余白を埋める） */}
      <AbsoluteFill>
        <Media
          src={src}
          video={video}
          playbackRate={playbackRate}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: "scale(1.15)",
            filter: "blur(40px) brightness(0.45)",
          }}
        />
      </AbsoluteFill>
      {/* 前景。深度マップがあれば 2.5D カメラ、なければ静止画=ケンバーンズ / 動画=そのまま */}
      {panel.depth && !video ? (
        <DepthScene layout={panel.depth} src={src} progress={progress} />
      ) : (
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <Media
            src={src}
            video={video}
            playbackRate={playbackRate}
            style={{
              maxWidth: "100%",
              maxHeight: "100%",
              objectFit: "contain",
              transform: video ? undefined : kenBurns(panel.motion, progress),
              willChange: video ? undefined : "transform",
            }}
          />
        </AbsoluteFill>
      )}
      {/* パーティクル効果（絵の上） */}
      <Effects effects={panel.effects} />
      {/* テキスト（余白の黒帯） */}
      <Overlays overlays={panel.overlays} />
    </AbsoluteFill>
  );
};

export const Manhwa: React.FC = () => {
  const { timings, totalFrames } = getPanelTimings();
  const frame = useCurrentFrame();

  // ショーケース（白背景の表紙）ではグレードを抑える。
  // 周辺減光が白地を汚すと「印刷広告」感が消えるため。
  let damp = 0;
  panels.forEach((p, i) => {
    if (!p.showcase) return;
    const t = timings[i];
    if (frame < t.start || frame >= t.start + t.frames) return;
    const ramp =
      t.fadeIn > 0
        ? interpolate(frame, [t.start, t.start + t.fadeIn], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })
        : 1;
    damp = Math.max(damp, ramp);
  });

  const shots = (
    <AbsoluteFill style={{ backgroundColor: BACKGROUND_COLOR }}>
      {panels.map((panel, i) => (
        <Sequence key={i} from={timings[i].start} durationInFrames={timings[i].frames}>
          <PanelView
            panel={panel}
            frames={timings[i].frames}
            fadeIn={timings[i].fadeIn}
            seconds={timings[i].seconds}
          />
        </Sequence>
      ))}
    </AbsoluteFill>
  );

  return (
    <AbsoluteFill style={{ backgroundColor: BACKGROUND_COLOR }}>
      {grade ? (
        <Grade config={grade} damp={damp}>
          {shots}
        </Grade>
      ) : (
        shots
      )}
      <FadeInOut totalFrames={totalFrames} />
      {bgm && (
        <Audio
          src={staticFile(bgm.src)}
          volume={(f) => {
            const fade = (bgm.fadeOutSeconds ?? 0) * FPS;
            if (fade <= 0) return bgm.volume;
            return interpolate(f, [totalFrames - fade, totalFrames], [bgm.volume, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
          }}
        />
      )}
    </AbsoluteFill>
  );
};
