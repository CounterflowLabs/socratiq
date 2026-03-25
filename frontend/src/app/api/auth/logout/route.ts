export async function POST() {
  const headers = new Headers({ "Content-Type": "application/json" });
  headers.append("Set-Cookie", "logged_in=; Path=/; Max-Age=0");
  return new Response(JSON.stringify({ success: true }), { status: 200, headers });
}
