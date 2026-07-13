import { API_BASE_URL } from "@/lib/api";

const TOKEN_KEY = "aerointel_token";

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export async function login(email: string, password: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    throw new Error(res.status === 401 ? "Incorrect email or password" : "Login failed");
  }
  const data = (await res.json()) as { access_token: string };
  setToken(data.access_token);
  return data.access_token;
}

export async function fetchCurrentUser(token: string): Promise<CurrentUser | null> {
  const res = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return null;
  return res.json() as Promise<CurrentUser>;
}
