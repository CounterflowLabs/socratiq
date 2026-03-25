export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { email, password, isRegister } = body;

    const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";
    const endpoint = isRegister ? "/api/v1/auth/register" : "/api/v1/auth/exchange";
    const payload = isRegister
      ? { email, password }
      : { provider: "credentials", email, password };

    const res = await fetch(`${BACKEND}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "error");
      return new Response(JSON.stringify({ error: text }), {
        status: res.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const tokens = await res.json();

    const headers = new Headers({ "Content-Type": "application/json" });
    headers.append(
      "Set-Cookie",
      `access_token=${tokens.access_token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=900`
    );
    headers.append(
      "Set-Cookie",
      `refresh_token=${tokens.refresh_token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800`
    );

    return new Response(JSON.stringify({ success: true }), { status: 200, headers });
  } catch (e: unknown) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}
