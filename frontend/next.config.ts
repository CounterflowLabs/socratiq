import type { NextConfig } from "next";

// Backend proxy is now handled by a Route Handler at
// `app/api/[...path]/route.ts`. The rewrite that previously sat here had no
// configurable timeout, so long-running upstream calls (e.g. Ollama-backed
// exercise generation) were truncated by the dev server's default
// inactivity window and surfaced as 500/socket-hang-up to the browser.

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.31.197"],
};

export default nextConfig;
