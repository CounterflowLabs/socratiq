import type { NextConfig } from "next";

const backendUrl = (process.env.BACKEND_URL || "http://localhost:8000").replace(
  /\/$/,
  ""
);

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.31.197"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
