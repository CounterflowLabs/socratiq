const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function loginWithCredentials(email: string, password: string): Promise<{
  access_token: string;
  refresh_token: string;
} | null> {
  const res = await fetch(`${BACKEND_URL}/api/v1/auth/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: "credentials", email, password }),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function registerUser(email: string, password: string, name?: string): Promise<{
  access_token: string;
  refresh_token: string;
} | null> {
  const res = await fetch(`${BACKEND_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
  if (!res.ok) return null;
  return res.json();
}
