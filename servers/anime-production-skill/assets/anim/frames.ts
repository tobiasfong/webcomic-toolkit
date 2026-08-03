import type { PanelAnimation } from "../data/manhwa-panels";

/**
 * コマ打ち / Frame timing for hand-drawn limited animation.
 *
 * アニメは毎コマ描きません。1枚を2コマ保持すれば「ツー」＝24fpsで秒12枚、
 * 3コマなら「スリー」＝秒8枚。同じカットの中で混ぜるのが普通で、
 * 溜め=スリー → 当たり=ワン → 戻し=ツー のように緩急をつけます。
 * だから保持コマ数は「1カット1つ」ではなく「1枚ごと」に持たせています。
 *
 * ⚠ 24fps で作ること。30fps だと 12枚/秒 に割り切れる保持数がなく、
 * 3,3,2,2… の不揃いな保持になってガタつきます。
 */

/** 各コマの保持コマ数を配列に正規化 */
const holdsOf = (anim: PanelAnimation): number[] => {
  const n = anim.frames.length;
  const h = anim.holds ?? 2;
  if (Array.isArray(h)) {
    return new Array(n).fill(0).map((_, i) => Math.max(1, Math.round(h[i] ?? h[h.length - 1] ?? 2)));
  }
  return new Array(n).fill(Math.max(1, Math.round(h)));
};

/** 決定的な擬似乱数（remotion の random と同じく、レンダリング再現性のため） */
const rnd = (n: number) => {
  const x = Math.sin(n * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

export interface FrameState {
  /** 表示するコマの番号 */
  index: number;
  /** そのコマに入ってからの経過コマ数（スメア用） */
  age: number;
  /** 直前のコマ番号（スメア＝中割りブラー用） */
  prev: number;
  /** コマの切り替わり直後か */
  justChanged: boolean;
}

/**
 * パネル内のローカルフレーム番号から、表示すべきコマを決める。
 * localFrame: パネルの先頭からのコマ数 / fps: コンポジションのfps
 */
export const frameAt = (anim: PanelAnimation, localFrame: number, fps: number): FrameState => {
  const n = anim.frames.length;
  if (n <= 1) return { index: 0, age: localFrame, prev: 0, justChanged: false };

  const start = Math.round((anim.startAt ?? 0) * fps);
  const t = localFrame - start;
  if (t < 0) return { index: 0, age: 0, prev: 0, justChanged: false };

  const holds = holdsOf(anim);
  const mode = anim.mode ?? "once";

  // --- 瞬き: ほぼ0番、たまに素早く最後まで往復する ---
  // 一定間隔だと機械的に見えるので、間隔をばらけさせ、時々二回続けて瞬きさせる。
  if (mode === "blink") {
    const minGap = (anim.gapSeconds ?? 3.4) * fps;
    const flick = holds.reduce((a, b) => a + b, 0); // 1往復ぶんの長さ
    let cursor = Math.round(minGap * 0.6);
    let k = 0;
    while (cursor < t + flick * 2 + minGap * 2) {
      const double = rnd(k * 7.3) < 0.22; // たまに二度瞬き
      const reps = double ? 2 : 1;
      for (let r = 0; r < reps; r++) {
        const local = t - cursor;
        if (local >= 0 && local < flick) {
          // 0→1→…→1→0 と往復（閉じてすぐ開く）
          const seq = [...holds.keys()];
          const pingpong = [...seq, ...seq.slice(1, -1).reverse()];
          let acc = 0;
          for (const idx of pingpong) {
            const h = holds[idx];
            if (local < acc + h) {
              return { index: idx, age: local - acc, prev: idx, justChanged: local === acc };
            }
            acc += h;
          }
        }
        cursor += flick;
      }
      cursor += Math.round(minGap * (0.7 + rnd(k * 3.1) * 0.9));
      k++;
      if (k > 400) break;
    }
    return { index: 0, age: 0, prev: 0, justChanged: false };
  }

  // --- 口パク: 会話のリズムで不規則に開閉 ---
  if (mode === "mouth") {
    let acc = 0;
    let k = 0;
    while (acc <= t + 240) {
      // 開/閉それぞれ保持コマ数を少し揺らす（メトロノームに聞こえないように）
      const idx = k % n;
      const jitter = 1 + Math.floor(rnd(k * 5.7) * 2); // +0〜1コマ
      const h = holds[idx] + jitter;
      if (t < acc + h) {
        return { index: idx, age: t - acc, prev: (k - 1 + n) % n, justChanged: t === acc };
      }
      acc += h;
      k++;
      if (k > 2000) break;
    }
    return { index: 0, age: 0, prev: 0, justChanged: false };
  }

  // --- once / loop / pingpong ---
  const order =
    mode === "pingpong"
      ? [...holds.keys(), ...[...holds.keys()].slice(1, -1).reverse()]
      : [...holds.keys()];
  const total = order.reduce((a, i) => a + holds[i], 0);

  let tt = t;
  if (mode === "loop" || mode === "pingpong") {
    tt = ((t % total) + total) % total;
  } else if (t >= total) {
    // once: 最後のコマで止める
    const last = order[order.length - 1];
    return { index: last, age: t - total, prev: last, justChanged: false };
  }

  let acc = 0;
  for (let i = 0; i < order.length; i++) {
    const idx = order[i];
    const h = holds[idx];
    if (tt < acc + h) {
      return {
        index: idx,
        age: tt - acc,
        prev: order[(i - 1 + order.length) % order.length],
        justChanged: tt === acc,
      };
    }
    acc += h;
  }
  return { index: 0, age: 0, prev: 0, justChanged: false };
};
