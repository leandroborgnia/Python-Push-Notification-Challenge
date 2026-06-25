// Session persistence in localStorage (research R6). Stores the access token plus the login email so
// the app bar can show identity without a backend call (`/auth/me` returns only a user id). The XSS
// trade-off of localStorage token storage is documented in research R6 and accepted for this app.

export interface Session {
  token: string;
  email: string;
}

const STORAGE_KEY = "nsvc.session";

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (typeof parsed.token === "string" && typeof parsed.email === "string") {
      return { token: parsed.token, email: parsed.email };
    }
    return null;
  } catch {
    // Corrupt or unavailable storage → treat as no session rather than crashing the app.
    return null;
  }
}

export function saveSession(session: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}
