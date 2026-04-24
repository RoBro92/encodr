import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useSession } from "../features/auth/AuthProvider";
import { LogoHorizontal } from "./Logo";
import { useCheckUpdateStatusMutation, useRuntimeStatusQuery, useUpdateStatusQuery } from "../lib/api/hooks";
import { APP_ROUTES } from "../lib/utils/routes";

type AppIconName = "activity" | "files" | "jobs" | "review" | "workers" | "system" | "settings" | "sun" | "moon" | "logout" | "x";

const navigation: Array<{ label: string; to: string; icon: AppIconName }> = [
  { label: "Dashboard", to: APP_ROUTES.dashboard, icon: "activity" },
  { label: "Library", to: APP_ROUTES.files, icon: "files" },
  { label: "Jobs", to: APP_ROUTES.jobs, icon: "jobs" },
  { label: "Review", to: APP_ROUTES.review, icon: "review" },
  { label: "Workers", to: APP_ROUTES.workers, icon: "workers" },
  { label: "System", to: APP_ROUTES.system, icon: "system" },
  { label: "Settings", to: APP_ROUTES.config, icon: "settings" },
];

const UPDATE_HIDE_KEY = "encodr:update:hide-until";
const UPDATE_SKIP_KEY = "encodr:update:skip-version";
const THEME_KEY = "encodr:theme";

type ThemePreference = "light" | "dark";

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
  const [isStorageBannerVisible, setIsStorageBannerVisible] = useState(true);
  const [theme, setTheme] = useState<ThemePreference>(() => readThemePreference());

  const updateStatus = updateQuery.data;
  const latestVersion = updateStatus?.latest_version ?? null;
  const updateAvailable = updateStatus?.update_available === true && Boolean(latestVersion);
  const pageHeader = getCurrentPageHeader(location.pathname);
  const hideStorageSetupBanner =
    location.pathname === APP_ROUTES.system ||
    location.pathname === APP_ROUTES.config ||
    location.pathname === "/settings";
  const showStorageSetupBanner =
    runtimeQuery.data?.storage_setup_incomplete &&
    !hideStorageSetupBanner &&
    isStorageBannerVisible;

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

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    writeThemePreference(theme);
  }, [theme]);

  async function handleLogout() {
    await logout();
    navigate(APP_ROUTES.login, { replace: true });
  }

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
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
      <div className="app-top-shell">
        <header className="topbar">
          <div className="topbar-page-context">
            <span className="topbar-page-title">{pageHeader.title}</span>
            {pageHeader.description ? (
              <>
                <span className="topbar-page-divider" aria-hidden="true">
                  |
                </span>
                <span className="topbar-page-subtitle">{pageHeader.description}</span>
              </>
            ) : null}
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
        {showStorageSetupBanner ? (
          <div className="global-alert-banner" role="note">
            <div className="global-alert-content">
              <strong>Storage needs attention.</strong>
              <span>
                Check <code>{runtimeQuery.data?.standard_media_root ?? "/media"}</code> in System, or run{" "}
                <code>encodr mount-setup --validate-only</code>.
              </span>
            </div>
            <button
              className="alert-dismiss-button"
              type="button"
              aria-label="Dismiss"
              onClick={() => setIsStorageBannerVisible(false)}
            >
              <AppIcon name="x" />
            </button>
          </div>
        ) : null}
      </div>
      <aside className="sidebar">
        <div className="sidebar-logo-row">
          <LogoHorizontal className="logo-horizontal sidebar-logo" />
        </div>
        <nav className="nav-list" aria-label="Primary">
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? " nav-link-active" : ""}`}
              end={item.to === APP_ROUTES.dashboard}
            >
              <AppIcon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-user">
            <span className="sidebar-avatar" aria-hidden="true">
              {getUserInitial(user?.username)}
            </span>
            <span className="sidebar-username">{user?.username ?? "Unknown user"}</span>
          </div>
          <div className="sidebar-actions">
            <button
              className="sidebar-icon-button"
              type="button"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              <AppIcon name={theme === "dark" ? "sun" : "moon"} />
            </button>
            <button
              className="sidebar-icon-button"
              type="button"
              onClick={handleLogout}
              aria-label="Sign out"
              title="Sign out"
            >
              <AppIcon name="logout" />
            </button>
          </div>
        </div>
      </aside>
      <div className="content-shell">
        <main className="page-shell">
          <Outlet />
        </main>
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

function AppIcon({ name }: { name: AppIconName }) {
  switch (name) {
    case "activity":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 12h4l2.5-7 5 14 2.5-7h4" />
        </svg>
      );
    case "files":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H10l2 2h5.5A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z" />
        </svg>
      );
    case "jobs":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 6h13M8 12h13M8 18h13" />
          <path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
        </svg>
      );
    case "review":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 13l4 4L19 7" />
        </svg>
      );
    case "workers":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 9h8M8 15h8" />
          <rect x="4" y="5" width="16" height="14" rx="3" />
        </svg>
      );
    case "system":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" />
          <path d="M19.4 15a8.2 8.2 0 0 0 .1-1l2-1.5-2-3.5-2.4 1a7.4 7.4 0 0 0-1.7-1L15 6.5h-4L10.6 9a7.4 7.4 0 0 0-1.7 1l-2.4-1-2 3.5 2 1.5a8.2 8.2 0 0 0 .1 2l-2 1.5 2 3.5 2.4-1a7.4 7.4 0 0 0 1.7 1l.4 2.5h4l.4-2.5a7.4 7.4 0 0 0 1.7-1l2.4 1 2-3.5z" />
        </svg>
      );
    case "settings":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 7h16M4 17h16" />
          <path d="M8 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM16 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" />
        </svg>
      );
    case "sun":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      );
    case "moon":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M21 12.8A8.5 8.5 0 1 1 11.2 3 6.5 6.5 0 0 0 21 12.8z" />
        </svg>
      );
    case "logout":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M10 17l5-5-5-5M15 12H3" />
          <path d="M14 4h4a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3h-4" />
        </svg>
      );
    case "x":
      return (
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      );
  }
}

function getUserInitial(username: string | undefined): string {
  return username?.trim().charAt(0).toUpperCase() || "U";
}

function getCurrentPageHeader(pathname: string): { title: string; description: string } {
  if (pathname === APP_ROUTES.dashboard) {
    return {
      title: "Dashboard",
      description: "Library, jobs, review, and storage at a glance.",
    };
  }

  const routeTitles: Array<{ path: string; title: string; description: string }> = [
    {
      path: APP_ROUTES.files,
      title: "Library",
      description: "Choose a folder, scan it, inspect the files, then dry run or create jobs.",
    },
    {
      path: APP_ROUTES.jobs,
      title: "Jobs",
      description: "Monitor running work, inspect outcomes, and retry jobs that need another pass.",
    },
    {
      path: APP_ROUTES.review,
      title: "Review",
      description: "See why automation paused, inspect the latest context, then take a decision.",
    },
    {
      path: APP_ROUTES.workers,
      title: "Workers",
      description: "Add execution nodes, pair remote agents, and manage backend, concurrency, schedule, and storage access per worker.",
    },
    {
      path: APP_ROUTES.reports,
      title: "Reports",
      description: "Read-only analytics from file, plan, and job history.",
    },
    {
      path: APP_ROUTES.system,
      title: "System",
      description: "Runtime and storage status.",
    },
    {
      path: APP_ROUTES.config,
      title: "Settings",
      description: "Choose library roots, set processing rules, and confirm runtime health.",
    },
  ];

  return routeTitles.find((route) => pathname === route.path || pathname.startsWith(`${route.path}/`))
    ?? { title: "Encodr", description: "Operator console." };
}

function readThemePreference(): ThemePreference {
  try {
    return window.localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function writeThemePreference(theme: ThemePreference) {
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Ignore storage failures; the in-memory theme still applies for this session.
  }
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
