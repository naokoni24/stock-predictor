import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
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
            fontSize: 58,
            fontWeight: 700,
            color: "#fafafa",
            fontFamily: "system-ui",
            transform: "translateY(-14px)",
          }}
        >
          AI
        </div>
        <svg
          width="180"
          height="180"
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
    { ...size }
  );
}
