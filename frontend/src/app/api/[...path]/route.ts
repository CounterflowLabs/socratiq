import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(
  /\/$/,
  ""
);

// 10 minutes — long enough to wait through a slow Ollama call without
// truncating with the default Next.js dev proxy timeout.
const PROXY_TIMEOUT_MS = 600_000;

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function filterRequestHeaders(headers: Headers): Headers {
  const out = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      out.set(key, value);
    }
  });
  return out;
}

function filterResponseHeaders(headers: Headers): Headers {
  const out = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      out.set(key, value);
    }
  });
  return out;
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${BACKEND_URL}/api/${path.join("/")}${req.nextUrl.search}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

  let body: BodyInit | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.arrayBuffer();
  }

  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers: filterRequestHeaders(req.headers),
      body: body as BodyInit | undefined,
      signal: controller.signal,
      // @ts-expect-error duplex required for streamed bodies in Node fetch
      duplex: "half",
      cache: "no-store",
      redirect: "manual",
    });

    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: filterResponseHeaders(upstream.headers),
    });
  } catch (err) {
    const aborted = controller.signal.aborted;
    return NextResponse.json(
      {
        detail: aborted
          ? `Proxy timeout after ${PROXY_TIMEOUT_MS / 1000}s`
          : `Proxy error: ${err instanceof Error ? err.message : String(err)}`,
      },
      { status: 504 }
    );
  } finally {
    clearTimeout(timer);
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
