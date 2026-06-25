// Session context: holds the current Session, exposes login/logout, runs the on-load token-validity
// probe, and registers the global 401 handler so any expired call routes back to /auth (FR-005).

import { Spin } from "antd";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { auth } from "../api/auth";
import { registerUnauthorizedHandler } from "../api/http";
import { isApiError } from "../lib/errors";
import { clearSession, loadSession, saveSession, type Session } from "./session";

interface AuthContextValue {
  session: Session | null;
  login: (token: string, email: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [session, setSession] = useState<Session | null>(() => loadSession());
  // Probe the stored token once on load; show an app-level spinner until it resolves.
  const [probing, setProbing] = useState<boolean>(() => loadSession() !== null);

  const login = useCallback((token: string, email: string) => {
    const next: Session = { token, email };
    saveSession(next);
    setSession(next);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setSession(null);
    navigate("/auth", { replace: true });
  }, [navigate]);

  // Global 401 handler: http.ts already cleared storage; mirror it in state and bounce to /auth
  // with an "expired" flag the AuthPage surfaces as a message.
  useEffect(() => {
    registerUnauthorizedHandler(() => {
      setSession(null);
      navigate("/auth", { replace: true, state: { expired: true } });
    });
    return () => registerUnauthorizedHandler(null);
  }, [navigate]);

  // On-load validity probe (FR-005). A 401 is handled by the global handler above; other failures
  // (offline/5xx) keep the stored session rather than forcing a logout.
  useEffect(() => {
    let active = true;
    if (!loadSession()) {
      setProbing(false);
      return;
    }
    auth
      .me()
      .catch((err: unknown) => {
        if (active && isApiError(err) && err.status === 401) setSession(null);
      })
      .finally(() => {
        if (active) setProbing(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo(() => ({ session, login, logout }), [session, login, logout]);

  if (probing) {
    return <Spin fullscreen tip="Restoring your session…" />;
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
