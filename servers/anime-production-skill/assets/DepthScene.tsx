import { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  useVideoConfig,
  staticFile,
  delayRender,
  continueRender,
  cancelRender,
} from "remotion";
import { ThreeCanvas } from "@remotion/three";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { DepthLayout } from "../data/manhwa-panels";

/**
 * 深度カメラ / Depth camera — edit-time 2.5D instead of a pre-baked clip.
 *
 * `parallax.py` bakes a fixed camera move into a fixed-length mp4 BEFORE the
 * edit exists, so the move can never respond to the music. This does the same
 * job at edit time: the illustration becomes a subdivided plane displaced along
 * Z by its depth map, and a real PerspectiveCamera moves through it. The move is
 * a function of the panel's own progress, so retiming a shot to a different
 * number of bars retimes the camera for free.
 *
 * Displacing real geometry (rather than warping pixels) also buys genuine
 * perspective and occlusion — the thing flat parallax always gives away. It is
 * still an eye-level relief map, not a model: keep `strength` modest or
 * silhouette edges stretch, exactly as the Python version warns.
 */

const vertexShader = /* glsl */ `
uniform sampler2D uDepth;
uniform float uStrength;
varying vec2 vUv;
void main() {
  vUv = uv;
  // depth map convention: white = near. Centre it so the plane pushes both ways.
  float d = texture2D(uDepth, uv).r - 0.5;
  vec3 p = position;
  p.z += d * uStrength;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;

const fragmentShader = /* glsl */ `
uniform sampler2D uMap;
varying vec2 vUv;
void main() {
  gl_FragColor = texture2D(uMap, vUv);
  #include <colorspace_fragment>
}`;

const FOV = 45;

/**
 * 絵全体が画面に収まるカメラ距離 / distance at which the whole plane fits.
 * 縦型フレームに横長の絵を置くと横で決まる（= objectFit: contain 相当）。
 * これを基準にしないと絵が大きくはみ出す。
 */
const fitDistance = (planeW: number, planeH: number, canvasAspect: number) => {
  const t = Math.tan((FOV * Math.PI) / 360);
  return Math.max(planeH / (2 * t), planeW / (2 * t * canvasAspect));
};

/**
 * カメラ位置と注視点 / camera position + whether it tracks parallel or orbits.
 * 移動量は基準距離に比例させるので、どんな縦横比の絵でも同じ見え方になります。
 */
const cameraAt = (
  move: NonNullable<DepthLayout["move"]>,
  t: number,
  amount: number,
  base: number
) => {
  const e = t * t * (3 - 2 * t); // smoothstep — no hard starts/stops
  const lat = base * 0.09 * amount; // 横/縦の移動量
  const dolly = base * 0.16; // 寄り/引きの量
  switch (move) {
    case "pan":
      return { pos: [(e - 0.5) * 2 * lat, 0, base] as const, orbit: false };
    case "crane":
      return { pos: [0, (0.5 - e) * 2 * lat, base - 0.25 * dolly * e] as const, orbit: false };
    case "orbit":
      return {
        pos: [
          Math.sin((e - 0.5) * 1.5) * lat * 2,
          Math.sin(e * Math.PI) * lat * 0.4,
          base,
        ] as const,
        orbit: true,
      };
    case "drift":
      return {
        pos: [(e - 0.5) * 1.4 * lat, (0.5 - e) * lat, base - 0.6 * dolly * e] as const,
        orbit: false,
      };
    case "pull":
      return { pos: [0, 0, base - dolly + dolly * e] as const, orbit: false };
    case "push":
    default:
      return { pos: [0, 0, base - dolly * e] as const, orbit: false };
  }
};

/** カメラを毎フレーム更新（camera prop は初期化時にしか効かないため） */
const CameraRig: React.FC<{ pos: readonly [number, number, number]; orbit: boolean }> = ({
  pos,
  orbit,
}) => {
  const { camera } = useThree();
  camera.position.set(pos[0], pos[1], pos[2]);
  // 横移動は平行トラック（中心を見ると回り込みになる）。orbit のときだけ中心を見る。
  camera.lookAt(orbit ? 0 : pos[0], orbit ? 0 : pos[1], 0);
  camera.updateProjectionMatrix();
  return null;
};

const Plane: React.FC<{
  map: THREE.Texture;
  depth: THREE.Texture;
  strength: number;
  planeW: number;
  planeH: number;
}> = ({ map, depth, strength, planeW, planeH }) => {
  const uniforms = useMemo(
    () => ({ uMap: { value: map }, uDepth: { value: depth }, uStrength: { value: strength } }),
    [map, depth, strength]
  );

  return (
    <mesh>
      {/* 高分割: 変位が滑らかに出る / high subdivision so displacement stays smooth */}
      <planeGeometry args={[planeW, planeH, 240, 240]} />
      <shaderMaterial
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
        side={THREE.FrontSide}
      />
    </mesh>
  );
};

export const DepthScene: React.FC<{
  layout: DepthLayout;
  /** 表示する絵（staticFile 済みのURL） */
  src: string;
  /** パネル内の進行度 0–1 */
  progress: number;
}> = ({ layout, src, progress }) => {
  const { width, height } = useVideoConfig();
  const [tex, setTex] = useState<{ map: THREE.Texture; depth: THREE.Texture } | null>(null);
  const [handle] = useState(() => delayRender("DepthScene: loading textures"));

  useEffect(() => {
    const loader = new THREE.TextureLoader();
    Promise.all([loader.loadAsync(src), loader.loadAsync(staticFile(layout.src))])
      .then(([map, depth]) => {
        map.colorSpace = THREE.SRGBColorSpace;
        depth.colorSpace = THREE.NoColorSpace; // depth is data, not colour
        setTex({ map, depth });
        continueRender(handle);
      })
      .catch((e) => cancelRender(e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, layout.src]);

  if (!tex) return null;

  const img = tex.map.image as { width: number; height: number } | undefined;
  const aspect = img && img.height ? img.width / img.height : 1;
  const planeH = 2;
  const planeW = planeH * aspect;
  const base = fitDistance(planeW, planeH, width / height) * 1.02; // 少し余裕
  const { pos, orbit } = cameraAt(layout.move ?? "push", progress, layout.amount ?? 1, base);

  return (
    <AbsoluteFill>
      <ThreeCanvas
        width={width}
        height={height}
        camera={{ fov: 45, position: [pos[0], pos[1], pos[2]] }}
        gl={{ antialias: true }}
        style={{ backgroundColor: "transparent" }}
      >
        <CameraRig pos={pos} orbit={orbit} />
        <Plane
          map={tex.map}
          depth={tex.depth}
          strength={layout.strength ?? 0.25}
          planeW={planeW}
          planeH={planeH}
        />
      </ThreeCanvas>
    </AbsoluteFill>
  );
};
