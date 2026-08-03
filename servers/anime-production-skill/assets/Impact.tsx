import { AbsoluteFill, random, useCurrentFrame, useVideoConfig } from "remotion";
import type { ImpactFx } from "../data/manhwa-panels";

/**
 * 衝撃演出 / Impact kit — 集中線・フラッシュ・カメラの揺れ・破片。
 *
 * アニメはパンチの「移動」を描きません。当たった瞬間の演出で見せます。
 * だから原画が1枚しかなくても、ここが効けば殴ったように見える。
 * 全部プログラムで出せるので、追加の作画は不要です。
 */

/** 効果の強さ（0→1→0の立ち上がりと減衰） */
const envelope = (local: number, attack: number, decay: number) => {
  if (local < 0) return 0;
  // attack=0 なら当たったコマで最大（1コマ遅れると「効いていない」ように見える）
  if (attack > 0 && local < attack) return local / attack;
  const t = (local - attack) / Math.max(1, decay);
  return t >= 1 ? 0 : Math.pow(1 - t, 1.8);
};

/** 集中線 / speed lines converging on a focal point */
const SpeedLines: React.FC<{
  strength: number;
  originX: number;
  originY: number;
  kind: "radial" | "horizontal";
  color: string;
}> = ({ strength, originX, originY, kind, color }) => {
  const { width, height } = useVideoConfig();
  const COUNT = 84;
  const diag = Math.hypot(width, height);
  const ox = originX * width;
  const oy = originY * height;

  return (
    <AbsoluteFill style={{ overflow: "hidden", pointerEvents: "none" }}>
      {new Array(COUNT).fill(0).map((_, i) => {
        const a =
          kind === "radial"
            ? (i / COUNT) * Math.PI * 2 + random(`sl-a-${i}`) * 0.06
            : (random(`sl-a-${i}`) - 0.5) * 0.5 + (i % 2 ? 0 : Math.PI);
        // 中心付近を空ける（顔や被写体を潰さない）
        const inner = diag * (0.14 + random(`sl-i-${i}`) * 0.16) * (1 - strength * 0.35);
        const len = diag * (0.35 + random(`sl-l-${i}`) * 0.5);
        const thick = 2.5 + random(`sl-t-${i}`) * 13 * strength;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: ox + Math.cos(a) * inner,
              top: oy + Math.sin(a) * inner,
              width: len,
              height: thick,
              background: `linear-gradient(90deg, transparent, ${color})`,
              boxShadow: `0 0 6px ${color}`,
              transform: `rotate(${(a * 180) / Math.PI}deg)`,
              transformOrigin: "left center",
              opacity: (0.75 + 0.25 * random(`sl-o-${i}`)) * (0.5 + 0.5 * strength),
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/** 破片 / debris burst */
const Debris: React.FC<{ strength: number; local: number; originX: number; originY: number }> = ({
  strength,
  local,
  originX,
  originY,
}) => {
  const { width, height } = useVideoConfig();
  const COUNT = Math.round(26 * strength);
  const ox = originX * width;
  const oy = originY * height;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {new Array(COUNT).fill(0).map((_, i) => {
        const a = random(`db-a-${i}`) * Math.PI * 2;
        const v = (8 + random(`db-v-${i}`) * 26) * strength;
        const g = 0.75; // 重力
        const x = ox + Math.cos(a) * v * local;
        const y = oy + Math.sin(a) * v * local + 0.5 * g * local * local;
        const size = 3 + random(`db-s-${i}`) * 9;
        const op = Math.max(0, 1 - local / (26 + random(`db-d-${i}`) * 18));
        if (op <= 0) return null;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: size,
              height: size * (0.4 + random(`db-r-${i}`) * 0.8),
              background: "rgba(240,238,230,0.92)",
              opacity: op,
              transform: `rotate(${local * (2 + random(`db-w-${i}`) * 6)}deg)`,
              borderRadius: 1,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/**
 * カメラの揺れ / camera shake — returns a CSS transform to wrap the shot in.
 * 減衰する高周波の揺れ。当たった直後だけ強く。
 */
export const shakeTransform = (fx: ImpactFx | undefined, localFrame: number, fps: number) => {
  if (!fx?.shake) return undefined;
  const at = Math.round((fx.at ?? 0) * fps);
  const local = localFrame - at;
  const e = envelope(local, 0, (fx.shakeDecay ?? 0.35) * fps);
  if (e <= 0.001) return undefined;
  const amp = 26 * fx.shake * e;
  const dx = Math.sin(local * 2.7) * amp;
  const dy = Math.cos(local * 3.9) * amp * 0.7;
  const rot = Math.sin(local * 2.2) * 0.5 * fx.shake * e;
  const scale = 1 + 0.02 * fx.shake * e;
  return `translate(${dx}px, ${dy}px) rotate(${rot}deg) scale(${scale})`;
};

export const Impact: React.FC<{ fx?: ImpactFx; offset?: number }> = ({ fx, offset = 0 }) => {
  const frame = useCurrentFrame() - offset;
  const { fps } = useVideoConfig();
  if (!fx) return null;

  const at = Math.round((fx.at ?? 0) * fps);
  const local = frame - at;
  if (local < -2) return null;

  const ox = fx.originX ?? 0.5;
  const oy = fx.originY ?? 0.45;

  const flashE = envelope(local, 0, (fx.flashDecay ?? 0.22) * fps);
  const linesE = envelope(local, 0, (fx.speedlinesDecay ?? 0.3) * fps);

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* 集中線 */}
      {fx.speedlines && linesE > 0.01 && (
        <AbsoluteFill style={{ opacity: linesE }}>
          <SpeedLines
            strength={fx.speedlines}
            originX={ox}
            originY={oy}
            kind={fx.speedlinesKind ?? "radial"}
            color={fx.speedlinesColor ?? "#ffffff"}
          />
        </AbsoluteFill>
      )}

      {/* 破片 */}
      {fx.debris && local >= 0 && (
        <Debris strength={fx.debris} local={local} originX={ox} originY={oy} />
      )}

      {/* 白フラッシュ（当たった瞬間） */}
      {fx.flash && flashE > 0.001 && (
        <AbsoluteFill
          style={{
            backgroundColor: fx.flashColor ?? "#ffffff",
            opacity: Math.min(1, fx.flash * flashE),
            mixBlendMode: "screen",
          }}
        />
      )}
    </AbsoluteFill>
  );
};
