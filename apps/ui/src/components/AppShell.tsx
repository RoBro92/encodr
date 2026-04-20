import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useSession } from "../features/auth/AuthProvider";
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
        </header>
        <main className="page-shell">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
