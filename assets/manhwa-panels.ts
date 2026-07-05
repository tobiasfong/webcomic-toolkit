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

export interface Panel {
  /**
   * ファイル名（public/panels/ 内）。静止画 (.jpg/.png) または動画クリップ (.mp4/.webm/.mov)。
   * 動画（Kling/Pika等の生成クリップ）は自動判定され、そのまま再生されます。
   */
  src: string;
  /**
   * この絵/クリップを表示する秒数。
   * 動画パネルの場合はクリップの長さに合わせてください（短いと最終フレームで静止します）。
   */
  durationInSeconds: number;
  /** カメラの動き（ケンバーンズ効果）。省略時は zoomIn。動画パネルでは無視されます。 */
  motion?: PanelMotion;
  /** パーティクル効果（複数可）。例: ["twinkle", "shootingStars"] */
  effects?: PanelEffect[];
  /** 画像周りの余白に表示するテキスト（クレジット・日付・URLなど） */
  overlays?: TextOverlay[];
  /** 表紙用ショーケース表示（白背景+影+余白クレジット）。通常パネルは省略 */
  showcase?: ShowcaseLayout;
}

// --- グローバル設定 / Global settings ---
export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920; // 縦型 9:16 / vertical Shorts

/** パネル間のクロスフェード長（フレーム）。30fpsで20=約0.67秒 */
export const TRANSITION_FRAMES = 20;

/** 背景色（絵がフレームを覆わない場合に見える色） */
export const BACKGROUND_COLOR = "#000000";

// --- BGM 設定 / Background music ---
// public/bgm/ にmp3を置いてから src を設定。未設定(null)なら無音で書き出し。
// fadeOutSeconds: 曲が動画より長い場合、末尾でフェードアウトする秒数
export const bgm: { src: string; volume: number; fadeOutSeconds?: number } | null = null;
// 例: export const bgm = { src: "bgm/theme.mp3", volume: 1, fadeOutSeconds: 3 };

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
// 表紙のショーケース例 / cover showcase example (Kadokawa-LN-ad style):
//   {
//     src: "panels/cover.jpg",
//     durationInSeconds: 5.5,
//     showcase: { background: "#ffffff", artPosition: "top", artSize: 0.78 },
//     overlays: [
//       { text: "Story: ...\nIllustrations: ...", position: "bottom-center", fontSize: 30, plain: true },
//     ],
//   },
export const panels: Panel[] = [];
