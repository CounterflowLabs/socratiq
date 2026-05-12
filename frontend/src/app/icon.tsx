import { ImageResponse } from "next/og";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f5efe2",
          color: "#1f1a14",
          fontFamily: "Georgia, 'Source Serif 4', serif",
          fontWeight: 600,
          fontSize: 44,
          letterSpacing: "-0.04em",
        }}
      >
        S
      </div>
    ),
    { ...size },
  );
}
