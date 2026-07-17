import {
  AbsoluteFill,
  random,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { PanelEffect } from "../data/manhwa-panels";

// すべての効果は remotion の random(seed) で決定的に生成（レンダリングで再現可能）
// All effects use remotion's deterministic random(seed) so renders are reproducible.

// ✨ 星のまたたき / Twinkling stars
const Twinkle: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const COUNT = 70;
  return (
    <AbsoluteFill>
      {new Array(COUNT).fill(0).map((_, i) => {
        const x = random(`tw-x-${i}`) * width;
        const y = random(`tw-y-${i}`) * height;
        const size = 1 + random(`tw-s-${i}`) * 2.5;
        const speed = 0.05 + random(`tw-sp-${i}`) * 0.1;
        const phase = random(`tw-p-${i}`) * Math.PI * 2;
        const op = 0.25 + 0.75 * (0.5 + 0.5 * Math.sin(frame * speed + phase));
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: size,
              height: size,
              borderRadius: "50%",
              background: "#fff",
              opacity: op,
              boxShadow: `0 0 ${size * 2}px #fff`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

// 🌠 流れ星 / Shooting stars (streak across the upper area)
const ShootingStars: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const events = 5;
  const travel = 30; // frames per streak
  const tail = 150;
  const angleDeg = 155; // travel direction (down-left) in screen coords
  const theta = (angleDeg * Math.PI) / 180;
  const speed = 26; // px per frame
  return (
    <AbsoluteFill>
      {new Array(events).fill(0).map((_, i) => {
        const startFrame = i * 42 + Math.floor(random(`ss-t-${i}`) * 28);
        const local = frame - startFrame;
        if (local < 0 || local > travel) return null;
        const p = local / travel;
        const sx = (0.3 + random(`ss-x-${i}`) * 0.6) * width;
        const sy = (0.05 + random(`ss-y-${i}`) * 0.35) * height;
        const dx = Math.cos(theta) * speed * local;
        const dy = Math.sin(theta) * speed * local;
        const op = Math.sin(p * Math.PI) * 0.9;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: sx + dx,
              top: sy + dy,
              width: tail,
              height: 2.5,
              background: `linear-gradient(${angleDeg + 180}deg, #fff, rgba(255,255,255,0))`,
              transform: `rotate(${angleDeg}deg)`,
              transformOrigin: "left center",
              opacity: op,
              borderRadius: 2,
              boxShadow: "0 0 8px rgba(255,255,255,0.9)",
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

// 💫 きらめき / Sparkles (pulsing bright points)
const Sparkles: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const COUNT = 24;
  return (
    <AbsoluteFill>
      {new Array(COUNT).fill(0).map((_, i) => {
        const x = random(`sp-x-${i}`) * width;
        const y = random(`sp-y-${i}`) * height;
        const period = 50 + random(`sp-pr-${i}`) * 60;
        const offset = random(`sp-o-${i}`) * period;
        const t = ((frame + offset) % period) / period; // 0..1
        const scale = Math.sin(t * Math.PI); // 0→1→0
        const size = 6 + random(`sp-s-${i}`) * 8;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: size,
              height: size,
              opacity: scale,
              transform: `scale(${scale})`,
              background:
                "radial-gradient(circle, #fff 0%, rgba(255,255,255,0.6) 35%, rgba(255,255,255,0) 70%)",
              borderRadius: "50%",
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

// 🍂 漂う粒子 / Drifting particles — embers rise, petals fall
const Drift: React.FC<{ kind: "embers" | "petals" }> = ({ kind }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const COUNT = 34;
  const up = kind === "embers";
  const rgb = up ? "255,180,90" : "255,200,220";
  const range = height + 100;
  return (
    <AbsoluteFill>
      {new Array(COUNT).fill(0).map((_, i) => {
        const speed = 0.4 + random(`d-sp-${i}`) * 0.9;
        const size = 3 + random(`d-s-${i}`) * 5;
        const x0 = random(`d-x-${i}`) * width;
        const sway = Math.sin(frame * 0.04 + i) * (10 + random(`d-w-${i}`) * 22);
        const startY = random(`d-y-${i}`) * range;
        let y = up ? startY - frame * speed : startY + frame * speed;
        y = ((y % range) + range) % range; // wrap
        const op = 0.35 + 0.4 * (0.5 + 0.5 * Math.sin(frame * 0.06 + i));
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x0 + sway,
              top: y,
              width: size,
              height: size,
              borderRadius: "50%",
              background: `rgba(${rgb},${op})`,
              boxShadow: `0 0 ${size}px rgba(${rgb},0.6)`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

export const Effects: React.FC<{ effects?: PanelEffect[] }> = ({ effects }) => {
  if (!effects || effects.length === 0) return null;
  return (
    <AbsoluteFill>
      {effects.map((e, i) => {
        switch (e) {
          case "twinkle":
            return <Twinkle key={i} />;
          case "shootingStars":
            return <ShootingStars key={i} />;
          case "sparkles":
            return <Sparkles key={i} />;
          case "embers":
            return <Drift key={i} kind="embers" />;
          case "petals":
            return <Drift key={i} kind="petals" />;
          default:
            return null;
        }
      })}
    </AbsoluteFill>
  );
};
