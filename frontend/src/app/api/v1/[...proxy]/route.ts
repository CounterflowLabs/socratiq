const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

function getTokenFromCookies(cookieHeader: string | null): string | null {
  if (!cookieHeader) return null;
  const match = cookieHeader.split(";").find((c) => c.trim().startsWith("access_token="));
  return match ? match.split("=")[1]?.trim() : null;
}

async function proxyRequest(req: Request) {
  try {
    const cookieHeader = req.headers.get("cookie");
    console.log("[proxy] cookie header:", cookieHeader?.substring(0, 80));
    const token = getTokenFromCookies(cookieHeader);
    console.log("[proxy] token found:", !!token);
    const url = new URL(req.url);
    const backendUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

    const headers: Record<string, string> = {};
    const ct = req.headers.get("content-type");
    if (ct) headers["Content-Type"] = ct;
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const body = req.method !== "GET" && req.method !== "HEAD"
      ? await req.arrayBuffer()
      : undefined;

    const res = await fetch(backendUrl, { method: req.method, headers, body });

    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") || "application/json" },
    });
  } catch {
    return new Response(JSON.stringify({ detail: "Backend unavailable" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
