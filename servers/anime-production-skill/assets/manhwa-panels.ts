// ===========================================================================
// 漫画スライドショー設定 / Manhwa-style slideshow config
// ---------------------------------------------------------------------------
// あなたの絵を public/panels/ に置き、下の panels 配列に並べてください。
// Put your drawings in public/panels/ and list them below in order.
// ===========================================================================

export type PanelMotion =
  | "zoomIn"
  | "zoomOut"
  | "panUp"
  | "panDown"
  | "panLeft"
  | "panRight";

// パーティクル効果 / Ambient particle effects (rendered over the art)
export type PanelEffect =
  | "twinkle" // 星のまたたき
  | "shootingStars" // 流れ星
  | "sparkles" // きらめき
  | "embers" // 舞い上がる火の粉
  | "petals"; // 舞い散る花びら

// テキストの配置（画像周りの余白＝黒帯に表示）/ Text sits in the margin band, not over the art
export type OverlayPosition =
  | "top-left"
  | "top-center"
  | "top-right"
  | "bottom-left"
  | "bottom-center"
  | "bottom-right";

export interface TextOverlay {
  /** 表示テキスト。改行は \n。例: "Art・Story・Lyrics: Tomoyuki" */
  text: string;
  /** 配置。省略時は bottom-left */
  position?: OverlayPosition;
  /** フォントサイズ。省略時は 26 */
  fontSize?: number;
  /** 文字色。省略時は #ffffff（plain時は #1a1a1a） */
  color?: string;
  /** true = 黒箱・影なしのプレーン文字（白背景のショーケース向け） */
  plain?: boolean;
}

/**
 * ショーケース表示（角川ラノベ広告風）：ぼかし背景の全面表示ではなく、
 * 単色背景の上に表紙をドロップシャドウ付きで配置し、余白にクレジットを置く。
 * 指定するとケンバーンズは無効（印刷広告風の静止表示）。
 */
export interface ShowcaseLayout {
  /** 背景色。省略時は白 #ffffff */
  background?: string;
  /** 絵の配置: top(上・下に余白) / left / right / center。省略時は top */
  artPosition?: "top" | "left" | "right" | "center";
  /** 絵の大きさ（フレームに対する割合 0–1）。省略時は 0.72 */
  artSize?: number;
}

/**
 * 深度カメラ / Depth camera (2.5D).
 *
 * 静止画 + 深度マップから、編集時にカメラを動かします。事前に mp4 へ焼き込む
 * `parallax.py` と違い、尺（bars）を変えればカメラワークも自動で追従します。
 * 深度マップは webcomic-background-mcp の `tools/make_depth.py` 等で生成し、
 * public/panels/ に置いてください（白 = 手前）。
 */
export interface DepthLayout {
  /** 深度マップのファイル名（public/panels/ 内） */
  src: string;
  /** カメラの動き。省略時は push */
  move?: "push" | "pull" | "pan" | "crane" | "orbit" | "drift";
  /**
   * 変位の強さ。省略時 0.18。
   * ⚠ 顔のアップでは 0.15–0.2 を超えないこと。アニメの顔は「一方向から見えるよう
   * 描かれた嘘の立体」なので、起伏を与えると輪郭が伸びて破綻します。
   * 風景・引きの絵なら 0.3–0.4 まで上げられます。
   */
  strength?: number;
  /** カメラの移動量。省略時 0.35 */
  amount?: number;
}


/**
 * 手描きのコマ再生 / Hand-drawn frame sequence.
 *
 * ⚠ アニメを含む作品は **24fps** で書き出すこと（FPS を 24 に）。
 * 24fpsなら holds:2 = 「ツー」= 秒12枚。30fpsだと12枚/秒に割り切れずガタつきます。
 * holds は1枚ごとに変えられます: 溜め=3, 当たり=1, 戻し=2 のような緩急が効きます。
 */
export interface PanelAnimation {
  /** コマ画像（表示順）。public/panels/ 内。1枚目は panel.src と同じでも可 */
  frames: string[];
  /**
   * 再生方法:
   *  once     … 1回だけ再生し最後のコマで止まる（パンチ、氷、ターン）
   *  loop     … 繰り返し
   *  pingpong … 往復（揺れ）
   *  blink    … ほぼ1枚目、たまに素早く瞬き（間隔は不規則、時々二度）
   *  mouth    … 会話のリズムで不規則に開閉（口パク）
   */
  mode?: "once" | "loop" | "pingpong" | "blink" | "mouth";
  /** 各コマの保持コマ数。数値=共通、配列=1枚ごと */
  holds?: number | number[];
  /** パネル内で再生を始める秒 */
  startAt?: number;
  /** 瞬きの平均間隔（秒）。mode:"blink" のみ。省略時 3.4 */
  gapSeconds?: number;
  /** コマ間に方向性ブラーの中割りを挟む（0=なし）。少ない枚数の速い動きに効く */
  smear?: number;
}

/**
 * 衝撃演出 / Impact FX（src/effects/Impact.tsx）。
 * 原画1枚でも「殴った」ように見せるための演出。作画不要。
 */
export interface ImpactFx {
  /** 効果が始まる秒（パネル内）。当たるコマに合わせる */
  at: number;
  /** 集中線の強さ 0–1 */
  speedlines?: number;
  speedlinesKind?: "radial" | "horizontal";
  speedlinesColor?: string;
  speedlinesDecay?: number;
  /** 白フラッシュ 0–1 */
  flash?: number;
  flashColor?: string;
  flashDecay?: number;
  /** カメラの揺れ 0–1 */
  shake?: number;
  shakeDecay?: number;
  /** 破片の量 0–1 */
  debris?: number;
  /** 効果の中心（画面比 0–1）。省略時 0.5 / 0.45 */
  originX?: number;
  originY?: number;
}

/**
 * 背景（バックドロップ）/ Designed backdrop behind the artwork.
 *
 * 縦型フレームに縦長の絵を置くと上下に帯が残ります。既定ではぼかした自分自身で
 * 埋めますが、ここに画像を指定すると「飾りの背景」に差し替わります
 * （webcomic-background-mcp で生成した森・きらめき等）。絵を伸ばすのではなく、
 * 背景の上に絵を置く方式なので継ぎ目や画風のズレが出ません。
 */
export interface Backdrop {
  /** 背景画像（public/ 内）。省略時は color、それも無ければ従来のぼかし */
  src?: string;
  /** 画像がない場合の単色/グラデーション */
  color?: string;
  /** ゆっくり漂う量（0=静止）。奥行きが出る */
  drift?: number;
  /** 背景のぼかし */
  blur?: number;
  /** 背景を暗くする 0–1（前景の絵を引き立てる） */
  darken?: number;
  /** 前景の絵に影を落とす */
  shadow?: boolean;
}

export interface Panel {
  /**
   * ファイル名（public/panels/ 内）。静止画 (.jpg/.png) または動画クリップ (.mp4/.webm/.mov)。
   * 動画（Kling/Pika等の生成クリップ）は自動判定され、そのまま再生されます。
   */
  src: string;
  /**
   * この絵/クリップを表示する秒数。
   * 動画パネルの場合はクリップの長さに合わせてください（短いと最終フレームで静止します）。
   * `bars` を指定し beatSync が有効な場合は無視されます。
   */
  durationInSeconds: number;
  /**
   * 小節数（1小節 = 4拍）。beatSync 有効時はこちらが優先され、
   * カットが必ず拍の頭に来ます。ティーザーは 2小節が基本、見せ場は 3–4小節。
   */
  bars?: number;
  /**
   * 動画クリップの実際の長さ（秒）。パネル尺と違う場合、再生速度を調整して
   * カメラワーク全体をパネル尺に収めます（尻切れ防止）。
   */
  clipSeconds?: number;
  /** カメラの動き（ケンバーンズ効果）。省略時は zoomIn。動画パネルでは無視されます。 */
  motion?: PanelMotion;
  /** パーティクル効果（複数可）。例: ["twinkle", "shootingStars"] */
  effects?: PanelEffect[];
  /** 画像周りの余白に表示するテキスト（クレジット・日付・URLなど） */
  overlays?: TextOverlay[];
  /** 表紙用ショーケース表示（白背景+影+余白クレジット）。通常パネルは省略 */
  showcase?: ShowcaseLayout;
  /** 手描きのコマ再生（瞬き・口パク・パンチなど）。指定すると src の代わりに使われます */
  animation?: PanelAnimation;
  /** 衝撃演出（集中線・フラッシュ・揺れ・破片） */
  impact?: ImpactFx;
  /** このパネルだけ背景を変える（未指定なら下の defaultBackdrop） */
  backdrop?: Backdrop;
  /**
   * 深度カメラ（2.5D）。静止画パネルに深度マップを与えると、平面の代わりに
   * 変位メッシュ + 実カメラで描画されます。motion（ケンバーンズ）より優先。
   */
  depth?: DepthLayout;
}

// --- グローバル設定 / Global settings ---
export const FPS = 30;   // 手描きアニメを含むなら 24 に（holds:2 = 秒12枚）
export const WIDTH = 1080;
export const HEIGHT = 1920; // 縦型 9:16 / vertical Shorts

/**
 * パネル間のクロスフェード長（フレーム）。ディゾルブは拍の頭で「完了」します。
 * ビート同期時は短いほど切れ味が出ます（30fpsで6 = 0.2秒 = 150BPMの8分音符）。
 */
export const TRANSITION_FRAMES = 6;

// --- ビート同期 / Beat sync ---
// `tools/extract-beats.mjs <mp3>` で src/data/beats.ts を生成してから有効化。
// 有効にすると各パネルの `bars` から尺が決まり、カットが必ず拍に乗ります。
export const beatSync = { enabled: false };

// --- 仕上げ / Post-processing grade（src/effects/Grade.tsx 参照）---
// 数値はすべて省略可。null にすると仕上げ処理そのものを無効化。
export const grade: import("../effects/Grade").GradeConfig | null = {
  bloom: 0.3,
  grain: 0.1,
  vignette: 0.32,
  flash: 0.08,
  punch: 0.01,
  audioReactive: 0.55,
  saturation: 1.06,
  contrast: 1.04,
};

/** 背景色（絵がフレームを覆わない場合に見える色） */
export const BACKGROUND_COLOR = "#000000";

/**
 * 全パネル共通の背景。null なら従来どおり「ぼかした自分自身」で埋めます。
 * 例: { src: "backdrops/forest.png", drift: 0.4, darken: 0.35, shadow: true }
 */
export const defaultBackdrop: Backdrop | null = null;

// --- BGM 設定 / Background music ---
// public/bgm/ にmp3を置いてから src を設定。未設定(null)なら無音で書き出し。
// fadeOutSeconds: 曲が動画より長い場合、末尾でフェードアウトする秒数
export const bgm: { src: string; volume: number; fadeOutSeconds?: number } | null = null;

// --- パネル一覧 / Panels (in display order) ---
// 画像を public/panels/ に置き、表示順に下へ追加してください。
// Put images in public/panels/ and list them here in display order.
// 例 / example:
//   {
//     src: "panels/01-cover.jpg",
//     durationInSeconds: 4,
//     motion: "zoomIn",
//     effects: ["twinkle", "shootingStars"],
//     overlays: [
//       { text: "Read the full story on Honeyfeed →\nhoneyfeed.fm/...", position: "bottom-center", fontSize: 30 },
//       { text: "Art・Story・Lyrics: Tomoyuki", position: "bottom-left", fontSize: 22 },
//     ],
//   },
// 例 / examples:
//   { src: "panels/01.jpg", durationInSeconds: 3.2, bars: 2, effects: ["sparkles"] },
//   // 手描きのコマ再生（瞬き）:
//   { src: "panels/face.png", durationInSeconds: 4,
//     animation: { frames: ["panels/face.png", "panels/face_eyes_closed.png"], mode: "blink" } },
//   // パンチ: 溜め3→当たり1→戻し2 + 衝撃演出:
//   { src: "panels/punch_01.png", durationInSeconds: 2.5,
//     animation: { frames: ["panels/punch_01.png","panels/punch_02.png","panels/punch_03.png"],
//                  mode: "once", holds: [3,1,2], smear: 1 },
//     impact: { at: 0.75, speedlines: 0.8, flash: 0.4, shake: 0.5, debris: 0.6 } },
export const panels: Panel[] = [];
