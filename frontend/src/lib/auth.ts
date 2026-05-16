/** Client-side auth state: token storage and global 401 handling. */

const ACCESS_KEY = "socratiq_access_token";
const REFRESH_KEY = "socratiq_refresh_token";
const USER_KEY = "socratiq_user";
const RETURN_PATH_KEY = "socratiq_return_path";

export interface AuthUser {
  id: string;
  email: string;
  name?: string | null;
  avatar_url?: string | null;
  is_admin?: boolean;
  subscription_until?: string | null;
  monthly_usd_cap?: number | null;
  has_active_subscription?: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function getAccessToken(): string | null {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function getStoredUser(): AuthUser | null {
  if (!isBrowser()) return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function setSession(tokens: TokenPair, user: AuthUser): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function setTokens(tokens: TokenPair): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function setStoredUser(user: AuthUser): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function rememberReturnPath(path: string): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(RETURN_PATH_KEY, path);
}

export function consumeReturnPath(): string | null {
  if (!isBrowser()) return null;
  const path = window.localStorage.getItem(RETURN_PATH_KEY);
  if (path) window.localStorage.removeItem(RETURN_PATH_KEY);
  return path;
}

export function redirectToLogin(): void {
  if (!isBrowser()) return;
  const here = window.location.pathname + window.location.search;
  if (here && !here.startsWith("/login")) {
    rememberReturnPath(here);
  }
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

export function redirectToRedeem(): void {
  if (!isBrowser()) return;
  const here = window.location.pathname + window.location.search;
  if (here && !here.startsWith("/redeem") && !here.startsWith("/login")) {
    rememberReturnPath(here);
  }
  if (window.location.pathname !== "/redeem") {
    window.location.href = "/redeem";
  }
}
