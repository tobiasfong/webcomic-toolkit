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
  type Panel,
  type TextOverlay,
  type OverlayPosition,
} from "./data/manhwa-panels";
import { Effects } from "./effects/Effects";

// 日本語対応フォント（オーバーレイ文字用）/ Japanese-capable font for overlays
const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
  ignoreTooManyRequestsWarning: true,
});

const T = TRANSITION_FRAMES;

// 動画クリップ（Kling/Pika等）か静止画かを拡張子で判定 / video clip vs still image
const isVideo = (src: string) => /\.(mp4|webm|mov|m4v)$/i.test(src);

// パネルのメディア（静止画 or 動画）。動画は音声をミュート（BGM優先）
const Media: React.FC<{ src: string; video: boolean; style: React.CSSProperties }> = ({
  src,
  video,
  style,
}) => (video ? <OffthreadVideo src={src} style={style} muted /> : <Img src={src} style={style} />);

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

// 各パネルの開始フレームと長さを計算（クロスフェード分だけ重ねる）
// Compute each panel's start frame and length, overlapping by T for crossfades.
export const getPanelTimings = () => {
  let cursor = 0;
  const timings = panels.map((p, i) => {
    const frames = Math.round(p.durationInSeconds * FPS);
    const start = i === 0 ? 0 : cursor - T;
    cursor = start + frames;
    return { start, frames };
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

const PanelView: React.FC<{ panel: Panel; frames: number; isFirst: boolean; isLast: boolean }> = ({
  panel,
  frames,
  isFirst,
  isLast,
}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // フェードイン（最初以外）とフェードアウト（最後以外）でクロスフェード
  const fadeIn = isFirst ? 1 : interpolate(frame, [0, T], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = isLast
    ? 1
    : interpolate(frame, [frames - T, frames], [1, 0], { extrapolateLeft: "clamp" });
  const opacity = Math.min(fadeIn, fadeOut);

  const src = staticFile(panel.src);
  const video = isVideo(panel.src);

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
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: "scale(1.15)",
            filter: "blur(40px) brightness(0.45)",
          }}
        />
      </AbsoluteFill>
      {/* 前景（絵全体を表示。静止画はケンバーンズ、動画はそのまま再生） */}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <Media
          src={src}
          video={video}
          style={{
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
            transform: video ? undefined : kenBurns(panel.motion, progress),
            willChange: video ? undefined : "transform",
          }}
        />
      </AbsoluteFill>
      {/* パーティクル効果（絵の上） */}
      <Effects effects={panel.effects} />
      {/* テキスト（余白の黒帯） */}
      <Overlays overlays={panel.overlays} />
    </AbsoluteFill>
  );
};

export const Manhwa: React.FC = () => {
  const { timings, totalFrames } = getPanelTimings();

  return (
    <AbsoluteFill style={{ backgroundColor: BACKGROUND_COLOR }}>
      {panels.map((panel, i) => (
        <Sequence key={i} from={timings[i].start} durationInFrames={timings[i].frames}>
          <PanelView
            panel={panel}
            frames={timings[i].frames}
            isFirst={i === 0}
            isLast={i === panels.length - 1}
          />
        </Sequence>
      ))}
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
