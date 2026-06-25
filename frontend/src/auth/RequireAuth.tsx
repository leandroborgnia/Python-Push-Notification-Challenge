// Route guard for the signed-in shell: redirect to /auth when there is no session (ui-routes.md).

import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "./AuthProvider";

export function RequireAuth() {
  const { session } = useAuth();
  if (!session) return <Navigate to="/auth" replace />;
  return <Outlet />;
}
