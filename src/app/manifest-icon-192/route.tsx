import { ImageResponse } from "next/og";

// PWAマニフェスト用アイコン(192x192)。apple-icon.tsx(180x180)と同じ
// デザイン(AI文字+緑スパークライン)をサイズ違いで生成する。
// パス自体はviewBoxで自動スケールされるため座標の再計算は不要。
const SIZE = 192;
const SCALE = SIZE / 180;

export async function GET() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          background: "#1a1a1a",
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: 58 * SCALE,
            fontWeight: 700,
            color: "#fafafa",
            fontFamily: "system-ui",
            transform: `translateY(${-14 * SCALE}px)`,
          }}
        >
          AI
        </div>
        <svg
          width={SIZE}
          height={SIZE}
          viewBox="0 0 180 180"
          style={{ position: "absolute", top: 0, left: 0 }}
        >
          <path
            d="M 35 145 L 55 130 L 75 138 L 95 115 L 115 122 L 135 100"
            fill="none"
            stroke="#4ade80"
            strokeWidth={6}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    ),
    { width: SIZE, height: SIZE }
  );
}
