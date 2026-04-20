import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useSession } from "../features/auth/AuthProvider";
import { useCheckUpdateStatusMutation, useRuntimeStatusQuery, useUpdateStatusQuery } from "../lib/api/hooks";
import { APP_ROUTES } from "../lib/utils/routes";

const navigation = [
  { label: "Dashboard", to: APP_ROUTES.dashboard },
  { label: "Files", to: APP_ROUTES.files },
  { label: "Jobs", to: APP_ROUTES.jobs },
  { label: "Workers", to: APP_ROUTES.workers },
  { label: "Manual Review", to: APP_ROUTES.review },
  { label: "Reports", to: APP_ROUTES.reports },
  { label: "System", to: APP_ROUTES.system },
  { label: "Config", to: APP_ROUTES.config },
];

export function AppShell() {
  const navigate = useNavigate();
  const { logout, user } = useSession();
  const runtimeQuery = useRuntimeStatusQuery();
  const updateQuery = useUpdateStatusQuery();
  const checkUpdateMutation = useCheckUpdateStatusMutation();

  async function handleLogout() {
    await logout();
    navigate(APP_ROUTES.login, { replace: true });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-panel">
          <p className="section-eyebrow">Encodr</p>
          <h1 className="brand-title">Operator console</h1>
          <p className="sidebar-copy">
            Probe, plan, review, and run jobs with a conservative, auditable workflow.
          </p>
        </div>
        <nav className="nav-list" aria-label="Primary">
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? " nav-link-active" : ""}`}
              end={item.to === APP_ROUTES.dashboard}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="session-panel">
          <span className="session-label">Signed in as</span>
          <strong>{user?.username ?? "Unknown user"}</strong>
          <button className="button button-secondary" type="button" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </aside>
      <div className="content-shell">
        <header className="topbar">
          <div>
            <span className="topbar-title">Operational UI</span>
            <span className="topbar-subtitle">Internal-only control surface</span>
          </div>
          <div className="topbar-meta">
            <span className="topbar-version">
              v{runtimeQuery.data?.version ?? __ENCODR_VERSION__}
            </span>
          </div>
        </header>
        {updateQuery.data?.update_available ? (
          <section className="update-banner" role="status" aria-live="polite">
            <div>
              <strong>Update available</strong>
              <p>
                Encodr {updateQuery.data.latest_version} is available. Current version is{" "}
                {updateQuery.data.current_version}.
              </p>
            </div>
            <div className="section-card-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => {
                  checkUpdateMutation.mutate();
                }}
                disabled={checkUpdateMutation.isPending}
              >
                {checkUpdateMutation.isPending ? "Checking…" : "Check again"}
              </button>
            </div>
          </section>
        ) : null}
        {runtimeQuery.data?.storage_setup_incomplete ? (
          <div className="info-strip" role="note">
            <strong>Storage is not configured yet.</strong>
            <span>
              Encodr expects your media library at{" "}
              <code>{runtimeQuery.data.standard_media_root}</code>. Open the System page or run{" "}
              <code>encodr mount-setup --validate-only</code>.
            </span>
          </div>
        ) : null}
        <main className="page-shell">
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>Encodr v{runtimeQuery.data?.version ?? __ENCODR_VERSION__}</span>
          <span>Local operator release line</span>
        </footer>
      </div>
    </div>
  );
}
