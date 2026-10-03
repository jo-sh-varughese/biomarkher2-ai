/* ============================================================================
   Accounts on the real backend (app/auth.py via app/server.py).

   config() is the one call that decides which world the portal is in: a
   JSON answer from /api/auth/config means a server with real accounts; no
   answer (the static Netlify build, or a laptop with the backend stopped)
   means the browser-only demo, which AuthContext keeps for exactly that case.
   ==========================================================================*/

import { ApiError, apiRequest, markOffline } from "./api.js";

export async function config() {
  try {
    return await apiRequest("/api/auth/config");
  } catch (err) {
    if (err instanceof ApiError || !err.fromServer) {
      markOffline();
      return { mode: "demo" };
    }
    throw err;
  }
}

export const me = () => apiRequest("/api/auth/me");
export const login = (body) => apiRequest("/api/auth/login", { method: "POST", body });
export const logout = () => apiRequest("/api/auth/logout", { method: "POST", body: {} });
export const setup = (body) => apiRequest("/api/auth/setup", { method: "POST", body });
export const requestAccess = (body) => apiRequest("/api/auth/request-access", { method: "POST", body });
export const inspectLink = (token) => apiRequest("/api/auth/link/inspect", { method: "POST", body: { token } });
export const acceptLink = (token, password) =>
  apiRequest("/api/auth/link", { method: "POST", body: { token, password } });
export const changePassword = (current, next) =>
  apiRequest("/api/auth/password", { method: "POST", body: { current, new: next } });
export const updateProfile = (patch) => apiRequest("/api/auth/profile", { method: "PATCH", body: patch });
export const mySessions = () => apiRequest("/api/auth/sessions");
export const revokeMySession = (id) => apiRequest(`/api/auth/sessions/${id}`, { method: "DELETE" });
export const revokeOtherSessions = () =>
  apiRequest("/api/auth/sessions/revoke-others", { method: "POST", body: {} });

/** The message to show for a failed call: the translated text for the
    server's error code when there is one, the server's own words otherwise. */
export function errorText(err, t) {
  if (err?.code) {
    const key = `errors.${err.code}`;
    const text = t(key, err.extra || {});
    if (text !== key) return text;
  }
  if (err?.i18nKey) return t(err.i18nKey);
  return err?.message || String(err);
}
