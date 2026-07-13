"use client";

import { createContext, useContext, useEffect, useState } from "react";

import type { CurrentUser } from "@/lib/auth";
import { clearToken, fetchCurrentUser, getToken } from "@/lib/auth";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    const me = await fetchCurrentUser(token);
    setUser(me);
    setLoading(false);
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional session restore on mount
    void refresh();
  }, []);

  function logout() {
    clearToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
