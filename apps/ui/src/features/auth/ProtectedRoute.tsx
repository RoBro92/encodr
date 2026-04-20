import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { APP_ROUTES } from "../../lib/utils/routes";
import { LoadingBlock } from "../../components/LoadingBlock";
import { useSession } from "./AuthProvider";

export function ProtectedRoute({ children }: { children: ReactElement }) {
  const location = useLocation();
  const { ready, isAuthenticated } = useSession();

  if (!ready) {
    return <LoadingBlock label="Loading your session" />;
  }

  if (!isAuthenticated) {
    return <Navigate to={APP_ROUTES.login} replace state={{ from: location.pathname }} />;
  }

  return children;
}
