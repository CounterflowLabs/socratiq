import type { NextConfig } from "next";

// Backend proxy is now handled by a Route Handler at
// `app/api/[...path]/route.ts`. The rewrite that previously sat here had no
// configurable timeout, so long-running upstream calls (e.g. Ollama-backed
// exercise generation) were truncated by the dev server's default
// inactivity window and surfaced as 500/socket-hang-up to the browser.

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Whitelist the entire 192.168.x.x LAN range so phones / iPads / other
  // laptops on the same WiFi can hit the dev server. Next 16 rejects any
  // browser origin not in this list when it does HMR / Server Actions
  // round-trips, which surfaces as silent fetch failures in the app.
  allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.31.*", "192.168.*.*"],
};

export default nextConfig;
