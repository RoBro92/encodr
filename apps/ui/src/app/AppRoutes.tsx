import { Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { ConfigPage } from "../features/config/ConfigPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { LoginPage } from "../features/auth/LoginPage";
import { ProtectedRoute } from "../features/auth/ProtectedRoute";
import { FilesPage } from "../features/files/FilesPage";
import { JobsPage } from "../features/jobs/JobsPage";
import { ReviewPage } from "../features/review/ReviewPage";
import { ReportsPage } from "../features/reports/ReportsPage";
import { SystemPage } from "../features/system/SystemPage";
import { WorkersPage } from "../features/workers/WorkersPage";
import { APP_ROUTES } from "../lib/utils/routes";

export function AppRoutes() {
  return (
    <Routes>
      <Route path={APP_ROUTES.login} element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path={APP_ROUTES.dashboard} element={<DashboardPage />} />
        <Route path={APP_ROUTES.files} element={<FilesPage />} />
        <Route path={`${APP_ROUTES.files}/:fileId`} element={<FilesPage />} />
        <Route path={APP_ROUTES.jobs} element={<JobsPage />} />
        <Route path={`${APP_ROUTES.jobs}/:jobId`} element={<JobsPage />} />
        <Route path={APP_ROUTES.workers} element={<WorkersPage />} />
        <Route path={`${APP_ROUTES.workers}/:workerId`} element={<WorkersPage />} />
        <Route path={APP_ROUTES.review} element={<ReviewPage />} />
        <Route path={`${APP_ROUTES.review}/:itemId`} element={<ReviewPage />} />
        <Route path={APP_ROUTES.reports} element={<ReportsPage />} />
        <Route path={APP_ROUTES.system} element={<SystemPage />} />
        <Route path={APP_ROUTES.config} element={<ConfigPage />} />
      </Route>
    </Routes>
  );
}
