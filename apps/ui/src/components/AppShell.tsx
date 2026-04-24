import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useSession } from "../features/auth/AuthProvider";
import { useCheckUpdateStatusMutation, useRuntimeStatusQuery, useUpdateStatusQuery } from "../lib/api/hooks";
import { APP_ROUTES } from "../lib/utils/routes";

const navigation = [
  { label: "Dashboard", to: APP_ROUTES.dashboard },
  { label: "Library", to: APP_ROUTES.files },
  { label: "Jobs", to: APP_ROUTES.jobs },
  { label: "Review", to: APP_ROUTES.review },
  { label: "Workers", to: APP_ROUTES.workers },
  { label: "System", to: APP_ROUTES.system },
  { label: "Settings", to: APP_ROUTES.config },
];

const UPDATE_HIDE_KEY = "encodr:update:hide-until";
const UPDATE_SKIP_KEY = "encodr:update:skip-version";

type HiddenUpdateState = {
  version: string;
  until: string;
};

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout, user } = useSession();
  const runtimeQuery = useRuntimeStatusQuery();
  const updateQuery = useUpdateStatusQuery();
  const checkUpdateMutation = useCheckUpdateStatusMutation();
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
  const [isUpdateModalOpen, setIsUpdateModalOpen] = useState(false);

  const updateStatus = updateQuery.data;
  const latestVersion = updateStatus?.latest_version ?? null;
  const updateAvailable = updateStatus?.update_available === true && Boolean(latestVersion);
  const hideStorageSetupBanner =
    location.pathname === APP_ROUTES.system ||
    location.pathname === APP_ROUTES.config ||
    location.pathname === "/settings";

  useEffect(() => {
    if (!updateAvailable || !latestVersion) {
      setIsUpdateModalOpen(false);
      return;
    }

    if (dismissedVersion === latestVersion) {
      setIsUpdateModalOpen(false);
      return;
    }

    const hiddenState = readHiddenUpdateState();
    if (hiddenState && hiddenState.version === latestVersion && Date.parse(hiddenState.until) > Date.now()) {
      setIsUpdateModalOpen(false);
      return;
    }

    if (readSkippedUpdateVersion() === latestVersion) {
      setIsUpdateModalOpen(false);
      return;
    }

    setIsUpdateModalOpen(true);
  }, [dismissedVersion, latestVersion, updateAvailable]);

  async function handleLogout() {
    await logout();
    navigate(APP_ROUTES.login, { replace: true });
  }

  function closeUpdateModal() {
    setDismissedVersion(latestVersion);
    setIsUpdateModalOpen(false);
  }

  function hideUpdateFor24Hours() {
    if (!latestVersion) {
      return;
    }
    writeHiddenUpdateState({
      version: latestVersion,
      until: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
    });
    setIsUpdateModalOpen(false);
  }

  function skipCurrentUpdate() {
    if (!latestVersion) {
      return;
    }
    writeSkippedUpdateVersion(latestVersion);
    setIsUpdateModalOpen(false);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-panel">
          <p className="section-eyebrow">Encodr</p>
          <h1 className="brand-title">Operator</h1>
          <p className="sidebar-copy">Library, jobs, and review.</p>
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
            <span className="topbar-title">Encodr</span>
            <span className="topbar-subtitle">Operator console</span>
          </div>
          <div className="topbar-meta">
            {updateAvailable ? (
              <button
                className="update-pill"
                type="button"
                onClick={() => {
                  setIsUpdateModalOpen(true);
                }}
              >
                Update {latestVersion} available
              </button>
            ) : null}
            <span className="topbar-version">
              v{runtimeQuery.data?.version ?? __ENCODR_VERSION__}
            </span>
          </div>
        </header>
        {runtimeQuery.data?.storage_setup_incomplete && !hideStorageSetupBanner ? (
          <div className="info-strip" role="note">
            <strong>Storage needs attention.</strong>
            <span>
              Check <code>{runtimeQuery.data.standard_media_root}</code> in System, or run{" "}
              <code>encodr mount-setup --validate-only</code>.
            </span>
          </div>
        ) : null}
        <main className="page-shell">
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>v{runtimeQuery.data?.version ?? __ENCODR_VERSION__}</span>
          <span>
            {updateAvailable ? `Update ${latestVersion} available` : "Up to date"}
          </span>
        </footer>
      </div>
      {isUpdateModalOpen && updateStatus ? (
        <div className="modal-backdrop" role="presentation">
          <section className="modal-panel update-modal" role="dialog" aria-modal="true" aria-labelledby="update-modal-title">
            <div className="update-modal-header">
              <div>
                <p className="section-eyebrow">Update available</p>
                <h2 id="update-modal-title">
                  Encodr {updateStatus.latest_version} is ready to install
                </h2>
              </div>
              <button className="button button-secondary" type="button" onClick={closeUpdateModal}>
                Close
              </button>
            </div>
            <p className="update-modal-copy">
              Current version: <strong>{updateStatus.current_version}</strong>
            </p>
            {updateStatus.release_name ? (
              <p className="update-modal-copy">
                Release: <strong>{updateStatus.release_name}</strong>
              </p>
            ) : null}
            <div className="update-summary-card">
              <strong>What changed</strong>
              <p>{updateStatus.release_summary ?? "A newer Encodr release is available for this install."}</p>
            </div>
            {updateStatus.breaking_changes_summary ? (
              <div className="update-summary-card">
                <strong>Breaking changes</strong>
                <p>{updateStatus.breaking_changes_summary}</p>
              </div>
            ) : null}
            <div className="update-command-card">
              <strong>Run this in the root console</strong>
              <pre>encodr update --apply</pre>
            </div>
            <div className="section-card-actions">
              <button className="button button-secondary" type="button" onClick={closeUpdateModal}>
                Close
              </button>
              <button className="button button-secondary" type="button" onClick={hideUpdateFor24Hours}>
                Hide for 24h
              </button>
              <button className="button button-secondary" type="button" onClick={skipCurrentUpdate}>
                Skip update
              </button>
              {updateStatus.release_notes_url ? (
                <a className="button button-primary" href={updateStatus.release_notes_url} target="_blank" rel="noreferrer">
                  View release notes
                </a>
              ) : (
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => {
                    checkUpdateMutation.mutate();
                  }}
                  disabled={checkUpdateMutation.isPending}
                >
                  {checkUpdateMutation.isPending ? "Checking…" : "Check again"}
                </button>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function readHiddenUpdateState(): HiddenUpdateState | null {
  try {
    const raw = window.localStorage.getItem(UPDATE_HIDE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as HiddenUpdateState;
    if (typeof parsed.version !== "string" || typeof parsed.until !== "string") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeHiddenUpdateState(value: HiddenUpdateState) {
  window.localStorage.setItem(UPDATE_HIDE_KEY, JSON.stringify(value));
}

function readSkippedUpdateVersion(): string | null {
  return window.localStorage.getItem(UPDATE_SKIP_KEY);
}

function writeSkippedUpdateVersion(version: string) {
  window.localStorage.setItem(UPDATE_SKIP_KEY, version);
}
