import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { makeSession, mockFetchRoutes, renderApp, resetBrowserState } from "../test/test-utils";

const CURRENT_VERSION = __ENCODR_VERSION__;

function nextPatchVersion(version: string): string {
  const parts = version.split(".");
  const patch = Number.parseInt(parts.at(-1) ?? "0", 10);
  if (Number.isNaN(patch)) {
    return `${version}-next`;
  }
  return [...parts.slice(0, -1), String(patch + 1)].join(".");
}

describe("Encodr UI shell", () => {
  beforeEach(() => {
    resetBrowserState();
  });

  afterEach(() => {
    resetBrowserState();
  });

  it("shows the login screen when an unauthenticated user opens a protected route", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/auth/bootstrap-status",
        body: {
          bootstrap_allowed: false,
          first_user_setup_required: false,
          user_count: 1,
          version: CURRENT_VERSION,
        },
      },
    ]);

    renderApp({ route: "/" });

    expect(await screen.findByRole("heading", { name: /sign in to the operator console/i })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`encodr v${CURRENT_VERSION}`, "i"))).toBeInTheDocument();
  });

  it("shows the first-user setup flow when bootstrap is still allowed", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/auth/bootstrap-status",
        body: {
          bootstrap_allowed: true,
          first_user_setup_required: true,
          user_count: 0,
          version: CURRENT_VERSION,
        },
      },
      {
        method: "POST",
        path: "/api/auth/bootstrap-admin",
        body: {
          user: {
            id: "user-1",
            username: "admin",
            role: "admin",
            is_active: true,
            is_bootstrap_admin: true,
            last_login_at: null,
          },
        },
      },
      {
        method: "POST",
        path: "/api/auth/login",
        body: {
          access_token: "new-access",
          refresh_token: "new-refresh",
          token_type: "bearer",
          access_token_expires_in: 1800,
          refresh_token_expires_in: 1209600,
        },
      },
      {
        method: "GET",
        path: "/api/auth/me",
        body: {
          id: "user-1",
          username: "admin",
          role: "admin",
          is_active: true,
          is_bootstrap_admin: true,
          last_login_at: null,
        },
      },
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/login" });

    expect(await screen.findByRole("heading", { name: /set up the first admin user/i })).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/username/i));
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/^password$/i), "super-secure-password");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "super-secure-password");
    await userEvent.click(screen.getByRole("button", { name: /create first admin/i }));

    expect(await screen.findByRole("heading", { name: /^dashboard$/i })).toBeInTheDocument();
  });

  it("shows a bootstrap-status error instead of falling back silently to sign in", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/auth/bootstrap-status",
        status: 500,
        body: { detail: "bootstrap status unavailable" },
      },
    ]);

    renderApp({ route: "/login" });

    expect(await screen.findByRole("heading", { name: /unable to load sign-in state/i })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/bootstrap status unavailable/i);
  });

  it("renders the simplified dashboard navigation and entry points", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^dashboard$/i })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: /primary/i });
    const navLabels = within(nav)
      .getAllByRole("link")
      .map((item) => item.textContent?.trim());
    expect(navLabels).toEqual(["Dashboard", "Library", "Jobs", "Review", "Workers", "System", "Settings"]);
    expect(screen.getByRole("link", { name: /open library/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /open reports/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /^reports$/i, hidden: false })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/probe source path/i)).not.toBeInTheDocument();
  });

  it("keeps the storage warning visible when setup is incomplete", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/system/runtime",
        body: {
          ...runtimeStatus(),
          storage_setup_incomplete: true,
        },
      },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("note")).toHaveTextContent(/storage still needs setup/i);
  });

  it("shows an update banner when a newer version is available", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      {
        method: "GET",
        path: "/api/system/update",
        body: {
          current_version: CURRENT_VERSION,
          latest_version: nextPatchVersion(CURRENT_VERSION),
          update_available: true,
          channel: "internal",
          status: "ok",
          release_name: `Encodr v${nextPatchVersion(CURRENT_VERSION)}`,
          release_summary: "Installer fixes and update improvements.",
          checked_at: "2026-04-20T12:30:00Z",
          error: null,
          download_url: "https://example.invalid/encodr.tar.gz",
          release_notes_url: "https://example.invalid/encodr-notes",
        },
      },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: new RegExp(`encodr ${nextPatchVersion(CURRENT_VERSION)} is ready to install`, "i") })).toBeInTheDocument();
    expect(screen.getByText(/installer fixes and update improvements/i)).toBeInTheDocument();
    expect(screen.getAllByText(/encodr update --apply/i)[0]).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(`update ${nextPatchVersion(CURRENT_VERSION)} available`, "i") })).toBeInTheDocument();
  });

  it("lets an operator skip the current update while keeping a subtle indicator", async () => {
    const latestVersion = nextPatchVersion(CURRENT_VERSION);
    mockFetchRoutes([
      { method: "GET", path: "/api/analytics/dashboard", body: analyticsDashboard() },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      {
        method: "GET",
        path: "/api/system/update",
        body: {
          current_version: CURRENT_VERSION,
          latest_version: latestVersion,
          update_available: true,
          channel: "internal",
          status: "ok",
          release_name: `Encodr v${latestVersion}`,
          release_summary: "Installer fixes and update improvements.",
          checked_at: "2026-04-20T12:30:00Z",
          error: null,
          download_url: "https://example.invalid/encodr.tar.gz",
          release_notes_url: "https://example.invalid/encodr-notes",
        },
      },
    ]);

    renderApp({ route: "/", initialSession: makeSession() });

    await userEvent.click(await screen.findByRole("button", { name: /skip update/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(window.localStorage.getItem("encodr:update:skip-version")).toBe(latestVersion);
    expect(screen.getByRole("button", { name: new RegExp(`update ${latestVersion} available`, "i") })).toBeInTheDocument();
  });

  it("lets an operator choose Movies and TV folders from the settings page", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      { method: "GET", path: "/api/system/update", body: updateStatus() },
      { method: "GET", path: "/api/config/effective", body: effectiveConfig() },
      { method: "GET", path: "/api/config/setup/execution-preferences", body: executionPreferences() },
      { method: "GET", path: "/api/config/setup/processing-rules", body: processingRules() },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: null,
          tv_root: "/media/TV",
        },
      },
      {
        method: "GET",
        path: "/api/files/browse",
        body: {
          root_path: "/media",
          current_path: "/media",
          parent_path: null,
          entries: [
            { name: "Movies", path: "/media/Movies", entry_type: "directory", is_video: false },
            { name: "TV", path: "/media/TV", entry_type: "directory", is_video: false },
          ],
        },
      },
      {
        method: "PUT",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^settings$/i })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /choose folder/i })[0]);

    const dialog = await screen.findByRole("dialog", { name: /choose movies folder/i });
    expect(within(dialog).getByText("/media")).toBeInTheDocument();
    await userEvent.click(within(dialog).getAllByRole("button", { name: /^choose$/i })[0]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/config/setup/library-roots"),
        expect.objectContaining({ method: "PUT", headers: expect.any(Headers) }),
      );
    });
  });

  it("renders editable processing rules and saves movie changes through the settings API", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      { method: "GET", path: "/api/system/update", body: updateStatus() },
      { method: "GET", path: "/api/config/setup/library-roots", body: { media_root: "/media", movies_root: "/media/Movies", tv_root: "/media/TV" } },
      { method: "GET", path: "/api/config/setup/execution-preferences", body: executionPreferences() },
      { method: "GET", path: "/api/config/setup/processing-rules", body: processingRules() },
      {
        method: "PUT",
        path: "/api/config/setup/processing-rules",
        body: {
          movies: processingRuleset({
            profile_name: "movies-default",
            uses_defaults: false,
            current: {
              ...processingRules().movies.current,
              target_video_codec: "h264",
            },
          }),
          movies_4k: processingRules().movies_4k,
          tv: processingRules().tv,
          tv_4k: processingRules().tv_4k,
        },
      },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^settings$/i })).toBeInTheDocument();
    expect(screen.getByTestId("processing-rules-tab-movies")).toBeInTheDocument();
    expect(screen.getByTestId("processing-rules-tab-movies_4k")).toBeInTheDocument();
    expect(screen.getByTestId("processing-rules-tab-tv")).toBeInTheDocument();
    expect(screen.getByTestId("processing-rules-tab-tv_4k")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Movies max video reduction$/i)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/^Movies target video codec$/i), "h264");
    await userEvent.click(screen.getByRole("button", { name: /save movies rules/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/config/setup/processing-rules"),
        expect.objectContaining({
          method: "PUT",
          headers: expect.any(Headers),
          body: JSON.stringify({
            movies: {
              ...processingRules().movies.current,
              target_video_codec: "h264",
            },
            movies_4k: null,
            tv: null,
            tv_4k: null,
          }),
        }),
      );
    });
  });

  it("does not save unsaved TV rule edits when only movie rules are submitted", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      { method: "GET", path: "/api/system/update", body: updateStatus() },
      { method: "GET", path: "/api/config/setup/library-roots", body: { media_root: "/media", movies_root: "/media/Movies", tv_root: "/media/TV" } },
      { method: "GET", path: "/api/config/setup/execution-preferences", body: executionPreferences() },
      { method: "GET", path: "/api/config/setup/processing-rules", body: processingRules() },
      {
        method: "PUT",
        path: "/api/config/setup/processing-rules",
        body: {
          movies: processingRuleset({
            profile_name: "movies-default",
            uses_defaults: false,
            current: {
              ...processingRules().movies.current,
              target_video_codec: "h264",
            },
          }),
          movies_4k: processingRules().movies_4k,
          tv: processingRules().tv,
          tv_4k: processingRules().tv_4k,
        },
      },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^settings$/i })).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("processing-rules-tab-tv"));
    await userEvent.selectOptions(screen.getByLabelText(/^TV target video codec$/i), "av1");
    await userEvent.click(screen.getByTestId("processing-rules-tab-movies"));
    await userEvent.selectOptions(screen.getByLabelText(/^Movies target video codec$/i), "h264");
    await userEvent.click(screen.getByRole("button", { name: /save movies rules/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/config/setup/processing-rules"),
        expect.objectContaining({
          method: "PUT",
          headers: expect.any(Headers),
          body: JSON.stringify({
            movies: {
              ...processingRules().movies.current,
              target_video_codec: "h264",
            },
            movies_4k: null,
            tv: null,
            tv_4k: null,
          }),
        }),
      );
    });
  });

  it("shows the simplified settings structure and update status", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/system/runtime",
        body: {
          ...runtimeStatus(),
          storage_setup_incomplete: true,
        },
      },
      {
        method: "GET",
        path: "/api/system/storage",
        body: {
          ...storageStatus(),
          warnings: ["Media path is empty. If you expected a mounted library, check the host or LXC bind mount."],
        },
      },
      {
        method: "GET",
        path: "/api/system/update",
        body: {
          ...updateStatus(),
          latest_version: nextPatchVersion(CURRENT_VERSION),
          update_available: false,
          checked_at: "2026-04-21T08:00:00Z",
          release_summary: "## Runtime detection 2026-04-20\n\n- Update guidance improvements.\n- Safer `encodr update --apply` output.",
          breaking_changes_summary: "Restart after update if newly passed-through devices are not visible.",
        },
      },
      { method: "GET", path: "/api/config/setup/library-roots", body: { media_root: "/media", movies_root: "/media/Movies", tv_root: "/media/TV" } },
      { method: "GET", path: "/api/config/setup/execution-preferences", body: executionPreferences() },
      { method: "GET", path: "/api/config/setup/processing-rules", body: processingRules() },
    ]);

    renderApp({ route: "/config", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^settings$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /library folders/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^storage$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^updates$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /processing rules/i })).toBeInTheDocument();
    expect(screen.queryByText(/storage needs attention/i)).not.toBeInTheDocument();
    const settingsWarning = screen.getByRole("alert");
    expect(settingsWarning).toHaveTextContent(/media path is empty/i);
    const storageCard = screen.getByRole("heading", { name: /^storage$/i }).closest(".section-card");
    expect(storageCard).not.toHaveTextContent(/media path is empty/i);
    expect(screen.queryByText(/worker backends are configured per worker on the workers page/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/runtime health/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/scratch path/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/encodr update --apply/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/update guidance improvements/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /view changelog/i }));
    expect(screen.getByRole("dialog", { name: /release notes/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /release notes/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /close release notes/i })).not.toBeInTheDocument();
    expect(screen.getByText(/checked 21-04-2026/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /runtime detection 20-04-2026/i })).toBeInTheDocument();
    expect(screen.getByText(/update guidance improvements/i)).toBeInTheDocument();
    expect(screen.getAllByText(/breaking changes/i).length).toBeGreaterThan(0);

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /release notes/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /view changelog/i }));
    await userEvent.click(screen.getByRole("presentation"));
    expect(screen.queryByRole("dialog", { name: /release notes/i })).not.toBeInTheDocument();
  });

  it("renders the redesigned library workspace and lets tabs switch cleanly", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/files/scans", body: { items: [] } },
      { method: "GET", path: "/api/files/watchers", body: { items: [] } },
      { method: "GET", path: "/api/workers", body: { items: [workerInventory()] } },
      { method: "GET", path: "/api/jobs", body: { items: [], limit: 100, offset: 0 } },
      {
        method: "POST",
        path: "/api/files/scan",
        body: {
          folder_path: "/media/Movies",
          root_path: "/media",
          directory_count: 1,
          direct_directory_count: 1,
          video_file_count: 1,
          likely_show_count: 0,
          likely_season_count: 0,
          likely_episode_count: 0,
          likely_film_count: 1,
          files: [
            { name: "Film One (2024).mkv", path: "/media/Movies/Film One (2024).mkv", entry_type: "file", is_video: true },
          ],
        },
      },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^library$/i })).toBeInTheDocument();
    expect(screen.getByText(/movies root/i)).toBeInTheDocument();
    expect(screen.getByText(/tv root/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /current folder/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /dry run/i })).not.toBeInTheDocument();
    expect(screen.getByText(/choose another folder/i)).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: /^open$/i })[0]);

    expect(await screen.findByRole("tab", { name: /^browse$/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^dry run$/i }));
    expect(screen.getByText(/no dry run yet/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /batch plan/i }));
    expect(screen.getByText(/no batch results yet/i)).toBeInTheDocument();
  });

  it("shows a missing-roots prompt when library roots have not been set", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/files/scans", body: { items: [] } },
      { method: "GET", path: "/api/files/watchers", body: { items: [] } },
      { method: "GET", path: "/api/workers", body: { items: [] } },
      { method: "GET", path: "/api/jobs", body: { items: [], limit: 100, offset: 0 } },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: null,
          tv_root: null,
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByText(/library roots not set/i)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /settings/i })[0]).toBeInTheDocument();
  });

  it("scans a folder and runs a dry run from the library action bar", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/files/scans", body: { items: [] } },
      { method: "GET", path: "/api/files/watchers", body: { items: [] } },
      { method: "GET", path: "/api/workers", body: { items: [workerInventory()] } },
      {
        method: "GET",
        path: "/api/jobs",
        body: {
          items: [
            {
              ...jobDetail(),
              id: "dry-run-job-1",
              job_kind: "dry_run",
              source_filename: "Film One (2024).mkv",
              source_path: "/media/Movies/Film One (2024).mkv",
              worker_name: "worker-local",
              status: "completed",
              analysis_payload: {
                file_name: "Film One (2024).mkv",
                source_path: "/media/Movies/Film One (2024).mkv",
                planned_action: "transcode",
                video_handling: "transcode",
                output_filename: "Film One (2024).mkv",
                current_size_bytes: 2147483648,
                estimated_output_size_bytes: 1610612736,
                estimated_space_saved_bytes: 536870912,
                audio_tracks_removed_count: 1,
                subtitle_tracks_removed_count: 0,
                summary: "Would transcode video and remove one audio track.",
                requires_review: false,
                manual_review_reasons: [],
              },
            },
          ],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
      {
        method: "POST",
        path: "/api/files/scan",
        body: {
          folder_path: "/media/Movies",
          root_path: "/media",
          directory_count: 2,
          direct_directory_count: 2,
          video_file_count: 2,
          likely_show_count: 0,
          likely_season_count: 0,
          likely_episode_count: 0,
          likely_film_count: 2,
          files: [
            { name: "Film One (2024).mkv", path: "/media/Movies/Film One (2024).mkv", entry_type: "file", is_video: true },
            { name: "Film Two (2024).mkv", path: "/media/Movies/Film Two (2024).mkv", entry_type: "file", is_video: true },
          ],
        },
      },
      {
        method: "POST",
        path: "/api/jobs/dry-run",
        body: {
          created_count: 1,
          blocked_count: 0,
          items: [
            {
              source_path: "/media/Movies/Film One (2024).mkv",
              status: "created",
              message: null,
              job: {
                ...jobDetail(),
                id: "dry-run-job-1",
                job_kind: "dry_run",
                source_filename: "Film One (2024).mkv",
                source_path: "/media/Movies/Film One (2024).mkv",
                status: "pending",
              },
            },
          ],
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^library$/i })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /^open$/i })[0]);

    const selectedFolderCard = screen.getByRole("heading", { name: /current folder/i }).closest(".section-card") as HTMLElement | null;
    expect(selectedFolderCard).not.toBeNull();
    if (selectedFolderCard) {
      expect((await within(selectedFolderCard).findAllByText("/media/Movies")).length).toBeGreaterThan(0);
    }
    await userEvent.click(await screen.findByRole("checkbox", { name: /film one/i }));
    expect(screen.getAllByText(/1 file selected/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^dry run$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /batch plan/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create jobs/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^dry run$/i }));
    expect(await screen.findByRole("dialog", { name: /start dry run/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /start dry run/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/jobs/dry-run"),
        expect.objectContaining({
          method: "POST",
          headers: expect.any(Headers),
          body: JSON.stringify({
            selected_paths: ["/media/Movies/Film One (2024).mkv"],
            pinned_worker_id: undefined,
            schedule_windows: [],
            ignore_worker_schedule: false,
          }),
        }),
      );
    });

    expect(screen.getByRole("tab", { name: /^dry run$/i })).toHaveAttribute("aria-selected", "true");
    const dryRunPanel = screen.getByRole("tabpanel", { name: /^dry run$/i });
    expect(within(dryRunPanel).getByText(/worker-backed analysis/i)).toBeInTheDocument();
    expect(within(dryRunPanel).getByText(/would transcode video and remove one audio track/i)).toBeInTheDocument();
    expect(within(dryRunPanel).getByText(/film one \(2024\)\.mkv/i, { selector: "strong" })).toBeInTheDocument();
  });

  it("shows saved scans and watched folders in the library workspace", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      {
        method: "GET",
        path: "/api/files/scans",
        body: {
          items: [
            {
              scan_id: "scan-1",
              folder_path: "/ssd/downloads",
              root_path: "/ssd",
              source_kind: "watched",
              watched_job_id: "watch-1",
              scanned_at: "2026-04-22T11:30:00Z",
              stale: true,
              directory_count: 1,
              direct_directory_count: 1,
              video_file_count: 2,
              likely_show_count: 0,
              likely_season_count: 0,
              likely_episode_count: 0,
              likely_film_count: 2,
              files: [],
            },
          ],
        },
      },
      {
        method: "GET",
        path: "/api/files/watchers",
        body: {
          items: [
            {
              id: "watch-1",
              display_name: "SSD ingest",
              source_path: "/ssd/downloads",
              media_class: "movie",
              ruleset_override: "movies",
              preferred_worker_id: null,
              pinned_worker_id: null,
              preferred_backend: "cpu_only",
              schedule_windows: [{ days: ["mon", "tue"], start_time: "23:00", end_time: "07:30" }],
              schedule_summary: "mon,tue 23:00-07:30",
              auto_queue: true,
              stage_only: false,
              enabled: true,
              last_scan_record_id: "scan-1",
              last_scan_at: "2026-04-22T11:30:00Z",
              last_enqueue_at: "2026-04-22T11:31:00Z",
              last_seen_count: 2,
              created_at: "2026-04-22T11:00:00Z",
              updated_at: "2026-04-22T11:31:00Z",
            },
          ],
        },
      },
      { method: "GET", path: "/api/workers", body: { items: [workerInventory()] } },
      { method: "GET", path: "/api/jobs", body: { items: [], limit: 100, offset: 0 } },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^library$/i })).toBeInTheDocument();
    expect(screen.getAllByText("/ssd/downloads").length).toBeGreaterThan(0);
    expect(screen.getByText(/saved result may be stale/i)).toBeInTheDocument();
    expect(screen.getByText(/ssd ingest/i)).toBeInTheDocument();
    expect(screen.getByText(/mon,tue 23:00-07:30/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reopen/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
  });

  it("creates batch jobs from the selected folder without changing the job API", async () => {
    const fetchMock = mockFetchRoutes([
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/files/scans", body: { items: [] } },
      { method: "GET", path: "/api/files/watchers", body: { items: [] } },
      { method: "GET", path: "/api/workers", body: { items: [workerInventory()] } },
      { method: "GET", path: "/api/jobs", body: { items: [], limit: 100, offset: 0 } },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
      {
        method: "POST",
        path: "/api/files/scan",
        body: {
          folder_path: "/media/Movies",
          root_path: "/media",
          directory_count: 2,
          direct_directory_count: 2,
          video_file_count: 2,
          likely_show_count: 0,
          likely_season_count: 0,
          likely_episode_count: 0,
          likely_film_count: 2,
          files: [
            { name: "Film One (2024).mkv", path: "/media/Movies/Film One (2024).mkv", entry_type: "file", is_video: true },
            { name: "Film Two (2024).mkv", path: "/media/Movies/Film Two (2024).mkv", entry_type: "file", is_video: true },
          ],
        },
      },
      {
        method: "POST",
        path: "/api/jobs/batch",
        body: {
          scope: "folder",
          total_files: 2,
          created_count: 1,
          blocked_count: 1,
          items: [
            {
              source_path: "/media/Movies/Film One (2024).mkv",
              status: "created",
              message: null,
              job: {
                ...jobDetail(),
                id: "job-1",
                tracked_file_id: "file-1",
              },
            },
            {
              source_path: "/media/Movies/Film Two (2024).mkv",
              status: "blocked",
              message: "This file requires manual review or protected-file approval before a job can be created.",
              job: null,
            },
          ],
        },
      },
    ]);

    renderApp({ route: "/files", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^library$/i })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /^open$/i })[0]);
    await userEvent.click(await screen.findByRole("button", { name: /create jobs/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/jobs/batch"),
        expect.objectContaining({
          method: "POST",
          headers: expect.any(Headers),
          body: JSON.stringify({
            folder_path: "/media/Movies",
          }),
        }),
      );
    });

    expect(await screen.findByText(/jobs created/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /batch plan/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("link", { name: /open job/i })).toBeInTheDocument();
    expect(screen.getByText(/^Created$/i, { selector: ".metric-label" })).toBeInTheDocument();
    expect(screen.getByText(/^Blocked$/i, { selector: ".metric-label" })).toBeInTheDocument();
    expect(screen.getByText(/manual review or protected-file approval/i)).toBeInTheDocument();
  });

  it("renders the cleaned jobs queue, keeps retry wiring intact, and hides advanced detail by default", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: "/api/files",
        body: {
          items: [
            {
              ...reviewItemDetail().tracked_file,
              id: "file-1",
            },
          ],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: "/api/jobs/job-1",
        body: {
          ...jobDetail(),
          id: "job-1",
          status: "failed",
          verification_status: "failed",
          replacement_status: "pending",
          failure_message: "ffmpeg exited with code 1",
          requires_review: true,
          review_status: "open",
          execution_command: ["ffmpeg", "-i", "input.mkv", "output.mkv"],
          execution_stdout: "ffmpeg stdout",
          execution_stderr: "ffmpeg stderr",
          verification_payload: { checks: ["duration"], status: "failed" },
          replacement_payload: { replaced: false },
        },
      },
      {
        method: "GET",
        path: "/api/jobs",
        body: {
          items: [
            {
              ...jobDetail(),
              id: "job-1",
              status: "failed",
              verification_status: "failed",
              replacement_status: "pending",
              failure_message: "ffmpeg exited with code 1",
              requires_review: true,
              review_status: "open",
            },
            {
              ...jobDetail(),
              id: "job-2",
              tracked_file_id: "file-2",
              source_filename: "Running Film (2024).mkv",
              source_path: "/media/Movies/Running Film (2024).mkv",
              status: "completed",
              verification_status: "passed",
              replacement_status: "succeeded",
              completed_at: "2026-04-20T10:12:30Z",
            },
          ],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "POST",
        path: "/api/jobs/job-1/retry",
        body: {
          ...jobDetail(),
          id: "job-1",
          status: "pending",
          verification_status: "pending",
          replacement_status: "pending",
        },
      },
    ]);

    renderApp({ route: "/jobs/job-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^jobs$/i })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /jobs list/i })).toBeInTheDocument();
    expect(screen.getByText(/needs attention/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/create job from tracked file/i)).toBeInTheDocument();
    expect(screen.queryByText(/ffmpeg -i input\.mkv output\.mkv/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/example film \(2024\)\.mkv/i).length).toBeGreaterThan(0);

    const executionToggle = screen.getByRole("button", { name: /advanced execution details/i });
    await userEvent.click(executionToggle);
    expect(executionToggle).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(screen.getByRole("button", { name: /retry job/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/jobs/job-1/retry"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("shows running job progress and worker details in the jobs queue", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/files",
        body: {
          items: [],
          limit: 25,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: "/api/jobs",
        body: {
          items: [
            {
              ...jobDetail(),
              id: "job-running",
              source_filename: "Running Film (2024).mkv",
              source_path: "/media/Movies/Running Film (2024).mkv",
              status: "running",
              progress_stage: "encoding",
              progress_percent: 42,
              progress_out_time_seconds: 150,
              progress_fps: 83.2,
              progress_speed: 1.94,
              worker_name: "worker-remote-a",
              requested_execution_backend: "prefer_nvidia_gpu",
              actual_execution_backend: "nvidia_gpu",
              backend_selection_reason: "Using NVIDIA NVENC for hardware-accelerated video encoding.",
            },
          ],
          limit: 100,
          offset: 0,
        },
      },
    ]);

    renderApp({ route: "/jobs", initialSession: makeSession() });

    expect((await screen.findAllByText(/running film \(2024\)\.mkv/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/42%/i)).toBeInTheDocument();
    expect(screen.getAllByText(/worker-remote-a/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/83\.2 fps/i)).toBeInTheDocument();
    expect(screen.getAllByText(/nvidia/i).length).toBeGreaterThan(0);
  });

  it("shows a cancel action for cancellable local jobs and calls the cancel endpoint", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: "/api/worker/status",
        body: workerStatus(),
      },
      {
        method: "GET",
        path: "/api/files",
        body: {
          items: [],
          limit: 25,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: "/api/jobs",
        body: {
          items: [
            {
              ...jobDetail(),
              id: "job-running",
              assigned_worker_id: "worker-local-1",
              worker_name: "worker-local",
              source_filename: "Stuck Film (2024).mkv",
              source_path: "/media/Movies/Stuck Film (2024).mkv",
              status: "running",
              progress_stage: "initialising_backend",
              progress_percent: 0,
            },
          ],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "POST",
        path: "/api/jobs/job-running/cancel",
        body: {
          ...jobDetail(),
          id: "job-running",
          assigned_worker_id: null,
          worker_name: "worker-local",
          source_filename: "Stuck Film (2024).mkv",
          source_path: "/media/Movies/Stuck Film (2024).mkv",
          status: "interrupted",
          failure_category: "cancelled_by_operator",
          failure_message: "Cancelled by operator.",
          progress_stage: "cancelled",
          progress_percent: null,
        },
      },
    ]);

    renderApp({ route: "/jobs", initialSession: makeSession() });

    const [queueTitle] = await screen.findAllByText(/stuck film \(2024\)\.mkv/i);
    expect(queueTitle).toBeInTheDocument();
    const queueCard = queueTitle.closest(".queue-job-card");
    expect(queueCard).not.toBeNull();
    const cancelButton = within(queueCard as HTMLElement).getByRole("button", { name: /^cancel$/i });
    expect(cancelButton).toBeEnabled();

    await userEvent.click(cancelButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/jobs/job-running/cancel"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("uses tracked-file search requests instead of a fixed local picker list", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: /\/api\/files\?.*limit=25/,
        body: {
          items: [],
          limit: 25,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: /\/api\/jobs\?limit=100$/,
        body: {
          items: [],
          limit: 100,
          offset: 0,
        },
      },
    ]);

    renderApp({ route: "/jobs", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^jobs$/i })).toBeInTheDocument();
    const picker = screen.getByLabelText(/create job from tracked file/i);
    await userEvent.type(picker, "F");

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          typeof url === "string" && url.includes("/api/files?path_search=F&limit=25"),
        ),
      ).toBe(true);
    });
  });

  it("shows an empty jobs state when the queue is clear", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/files",
        body: {
          items: [],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "GET",
        path: "/api/jobs",
        body: {
          items: [],
          limit: 100,
          offset: 0,
        },
      },
    ]);

    renderApp({ route: "/jobs", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^jobs$/i })).toBeInTheDocument();
    expect(screen.getByText(/no jobs yet/i)).toBeInTheDocument();
  });

  it("renders the review inbox layout, keeps decisions wired, and hides advanced sections by default", async () => {
    const fetchMock = mockFetchRoutes([
      {
        method: "GET",
        path: "/api/review/items/item-1",
        body: reviewItemDetail(),
      },
      {
        method: "GET",
        path: "/api/review/items",
        body: {
          items: [
            reviewItemDetail(),
            {
              ...reviewItemDetail(),
              id: "item-2",
              review_status: "held",
              tracked_file: {
                ...reviewItemDetail().tracked_file,
                id: "file-2",
                source_filename: "Another Film (2024).mkv",
              },
            },
          ],
          limit: 100,
          offset: 0,
        },
      },
      {
        method: "POST",
        path: "/api/review/items/item-1/approve",
        body: {
          review_item: {
            ...reviewItemDetail(),
            review_status: "approved",
          },
          decision: null,
          job: null,
        },
      },
    ]);

    renderApp({ route: "/review/item-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^review$/i })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /review items list/i })).toBeInTheDocument();
    expect(screen.getAllByText(/missing english audio/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/planner protected/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /show protection details/i }));
    expect(screen.getByText(/planner protected/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/review/items/item-1/approve"),
        expect.objectContaining({ method: "POST", headers: expect.any(Headers) }),
      );
    });
  });

  it("shows an empty review inbox when no items match the current filters", async () => {
    mockFetchRoutes([
      {
        method: "GET",
        path: "/api/review/items",
        body: {
          items: [],
          limit: 100,
          offset: 0,
        },
      },
    ]);

    renderApp({ route: "/review", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^review$/i })).toBeInTheDocument();
    expect(screen.getByText(/no review items/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /selected item/i })).not.toBeInTheDocument();
  });

  it("uses consistent page headings for workers, system, and settings", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/workers", body: { items: [] } },
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      { method: "GET", path: "/api/system/runtime", body: runtimeStatus() },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
      { method: "GET", path: "/api/system/update", body: updateStatus() },
      { method: "GET", path: "/api/config/effective", body: effectiveConfig() },
      { method: "GET", path: "/api/config/setup/execution-preferences", body: executionPreferences() },
      { method: "GET", path: "/api/config/setup/processing-rules", body: processingRules() },
      {
        method: "GET",
        path: "/api/config/setup/library-roots",
        body: {
          media_root: "/media",
          movies_root: "/media/Movies",
          tv_root: "/media/TV",
        },
      },
    ]);

    const workersRender = renderApp({ route: "/workers", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /^workers$/i, level: 1 })).toBeInTheDocument();
    workersRender.unmount();

    const systemRender = renderApp({ route: "/system", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /^system$/i, level: 1 })).toBeInTheDocument();
    systemRender.unmount();

    renderApp({ route: "/config", initialSession: makeSession() });
    expect(await screen.findByRole("heading", { name: /^settings$/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /processing rules/i })).toBeInTheDocument();
  });

  it("moves system warnings to the top when runtime or storage is degraded", async () => {
    const mediaPathWarning = "Media path is empty. If you expected a mounted library, check the host or LXC bind mount.";
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/system/runtime",
        body: {
          ...runtimeStatus(),
          warnings: ["Database lag detected", mediaPathWarning],
        },
      },
      {
        method: "GET",
        path: "/api/system/storage",
        body: {
          ...storageStatus(),
          warnings: ["Scratch workspace is nearly full", mediaPathWarning],
        },
      },
    ]);

    renderApp({ route: "/system", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^system$/i })).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/database lag detected/i);
    expect(alert).toHaveTextContent(/media path is empty/i);
    expect(alert).toHaveTextContent(/encodr mount-setup --validate-only/i);
    expect(alert).toHaveTextContent(/host or lxc bind mount/i);
    expect(alert).toHaveTextContent(/scratch workspace is nearly full/i);
    expect(screen.getAllByText(/media path is empty/i)).toHaveLength(1);
  });

  it("keeps worker-specific backend diagnostics off the system page", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/system/runtime",
        body: {
          ...runtimeStatus(),
          storage_setup_incomplete: true,
        },
      },
      { method: "GET", path: "/api/system/storage", body: storageStatus() },
    ]);

    renderApp({ route: "/system", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^system$/i })).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(screen.queryByText(/storage needs attention/i)).not.toBeInTheDocument();
    expect(within(main).queryByRole("heading", { name: /^worker$/i })).not.toBeInTheDocument();
    expect(within(main).queryByText(/^pending jobs$/i)).not.toBeInTheDocument();
    expect(within(main).queryByText(/^queue$/i)).not.toBeInTheDocument();
    expect(within(main).queryByRole("button", { name: /run worker once/i })).not.toBeInTheDocument();
    expect(within(main).queryByRole("button", { name: /run self-test/i })).not.toBeInTheDocument();
    expect(within(main).getByRole("heading", { name: /^runtime$/i })).toBeInTheDocument();
    expect(within(main).getByRole("heading", { name: /^storage$/i })).toBeInTheDocument();
    expect(within(main).getByRole("heading", { name: /service health/i })).toBeInTheDocument();
    expect(within(main).getByRole("heading", { name: /compute health/i })).toBeInTheDocument();
    expect(within(main).queryByText(/scratch path/i)).not.toBeInTheDocument();
    expect(within(main).queryByText(/data path/i)).not.toBeInTheDocument();
    expect(within(main).queryByText(/^unavailable$/i)).not.toBeInTheDocument();
    expect(within(main).getByRole("progressbar", { name: /scratch workspace storage usage/i })).toHaveAttribute("aria-valuenow", "50");
    expect(within(main).getByRole("progressbar", { name: /application data storage usage/i })).toHaveAttribute("aria-valuenow", "50");
    expect(within(main).getByRole("progressbar", { name: /media library storage usage/i })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.queryByRole("heading", { name: /execution backends/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /runtime devices/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/current execution path/i)).not.toBeInTheDocument();
  });

  it("marks a remote worker without a heartbeat as not configured", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus({ configuration_state: "local_not_configured" }) },
      {
        method: "GET",
        path: "/api/workers",
        body: {
          items: [
            {
              ...workerInventory(),
              id: "worker-remote-1",
              worker_key: "remote-1",
              display_name: "Remote worker",
              worker_type: "remote",
              worker_state: "remote_registered",
              health_status: "healthy",
              last_seen_at: null,
              last_heartbeat_at: null,
              health_summary: "Healthy",
            },
          ],
        },
      },
    ]);

    renderApp({ route: "/workers", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^workers$/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/registered/i)).toBeInTheDocument();
  });

  it("shows worker current activity, telemetry, and recent jobs in worker detail", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/workers/worker-local-1",
        body: {
          ...workerInventory(),
          runtime_summary: {
            queue: "local-default",
            scratch_dir: "/temp",
            media_mounts: ["/media"],
            preferred_backend: "prefer_nvidia_gpu",
            allow_cpu_fallback: true,
            current_job_id: "job-running",
            current_backend: "nvidia_gpu",
            current_stage: "encoding",
            current_progress_percent: 44,
            current_progress_updated_at: "2026-04-22T12:01:00Z",
            telemetry: {
              collected_at: "2026-04-22T12:01:00Z",
              cpu_usage_percent: 68.2,
              process_cpu_usage_percent: 41.1,
              memory_usage_percent: 58.0,
              process_memory_bytes: 209715200,
              cpu_temperature_c: 62.1,
              gpu: {
                vendor: "NVIDIA",
                status: "healthy",
                usage_percent: 77.0,
                temperature_c: 69.0,
                message: "Telemetry is being read from nvidia-smi.",
              },
            },
            last_completed_job_id: "job-older",
          },
          recent_jobs: [
            {
              job_id: "job-older",
              source_filename: "Previous Film (2024).mkv",
              status: "completed",
              actual_execution_backend: "nvidia_gpu",
              requested_execution_backend: "prefer_nvidia_gpu",
              backend_fallback_used: false,
              completed_at: "2026-04-22T11:50:00Z",
              duration_seconds: 120,
              failure_message: null,
            },
          ],
        },
      },
      {
        method: "GET",
        path: "/api/workers",
        body: {
          items: [workerInventory()],
        },
      },
    ]);

    renderApp({ route: "/workers/worker-local-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^workers$/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /worker detail/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /current telemetry/i })).toBeInTheDocument();
    expect(screen.getByText(/job-running/i)).toBeInTheDocument();
    expect(screen.getByText(/44%/i)).toBeInTheDocument();
    expect(screen.getAllByText(/nvidia/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: /recent jobs/i })).toBeInTheDocument();
    expect(screen.getByText(/previous film \(2024\)\.mkv/i)).toBeInTheDocument();
  });

  it("shows only the selected primary backend diagnostics on worker detail", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/workers/worker-local-1",
        body: {
          ...workerInventory(),
          preferred_backend: "prefer_nvidia_gpu",
        },
      },
      {
        method: "GET",
        path: "/api/workers",
        body: {
          items: [{ ...workerInventory(), preferred_backend: "prefer_nvidia_gpu" }],
        },
      },
    ]);

    renderApp({ route: "/workers/worker-local-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^workers$/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/selected backend diagnostic/i)).toBeInTheDocument();
    expect(screen.getAllByText(/no nvidia runtime device is visible/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/primary backend failed\. falling back to cpu execution/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/attention: primary backend failed \(no nvidia runtime device is visible to the runtime\)\. worker is falling back to cpu execution\./i)).toBeInTheDocument();
    expect(screen.queryByText(/intel driver missing/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/amd render device is not visible/i)).not.toBeInTheDocument();
  });

  it("marks workers failed when the configured backend fails and CPU fallback is disabled", async () => {
    mockFetchRoutes([
      { method: "GET", path: "/api/worker/status", body: workerStatus() },
      {
        method: "GET",
        path: "/api/workers/worker-local-1",
        body: {
          ...workerInventory(),
          preferred_backend: "prefer_nvidia_gpu",
          allow_cpu_fallback: false,
        },
      },
      {
        method: "GET",
        path: "/api/workers",
        body: {
          items: [{ ...workerInventory(), preferred_backend: "prefer_nvidia_gpu", allow_cpu_fallback: false }],
        },
      },
    ]);

    renderApp({ route: "/workers/worker-local-1", initialSession: makeSession() });

    expect(await screen.findByRole("heading", { name: /^workers$/i, level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/primary backend failed and cpu fallback is disabled/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/attention: primary backend failed \(no nvidia runtime device is visible to the runtime\)\. cpu fallback is disabled\. worker cannot execute jobs\./i)).toBeInTheDocument();
  });
});

function analyticsDashboard() {
  return {
    overview: {
      total_tracked_files: 12,
      protected_file_count: 2,
      four_k_file_count: 3,
      jobs_by_status: [
        { value: "pending", count: 1 },
        { value: "completed", count: 5 },
        { value: "failed", count: 2 },
      ],
      plans_by_action: [
        { value: "skip", count: 2 },
        { value: "remux", count: 4 },
        { value: "transcode", count: 3 },
      ],
    },
    storage: {
      total_space_saved_bytes: 1073741824,
      average_space_saved_bytes: 536870912,
      savings_by_action: [
        { action: "remux", space_saved_bytes: 268435456, job_count: 1 },
        { action: "transcode", space_saved_bytes: 805306368, job_count: 1 },
      ],
    },
    outcomes: {
      jobs_by_status: [
        { value: "completed", count: 5 },
        { value: "failed", count: 2 },
      ],
      verification_by_status: [],
      replacement_by_status: [],
      top_failure_categories: [],
      container_distribution: [],
    },
    media: {
      latest_probe_english_audio_count: 5,
      latest_probe_forced_subtitle_count: 2,
      latest_probe_surround_audio_count: 3,
      latest_probe_atmos_audio_count: 1,
    },
    recent: {
      recent_completed_jobs: [
        {
          job_id: "job-1",
          file_name: "Example Film (2024).mkv",
          action: "remux",
          status: "completed",
          updated_at: "2026-04-20T11:15:00Z",
        },
      ],
      recent_failed_jobs: [
        {
          job_id: "job-2",
          file_name: "Broken Film (2024).mkv",
          action: "transcode",
          status: "failed",
          updated_at: "2026-04-20T12:15:00Z",
        },
      ],
    },
  };
}

function workerStatus(overrides: Record<string, unknown> = {}) {
  return {
    worker_id: "worker-local-1",
    status: "healthy",
    summary: "The local worker is healthy and available.",
    worker_name: "worker-local",
    configured: true,
    configuration_state: "local_healthy",
    mode: "single-node-local",
    local_only: true,
    enabled: true,
    available: true,
    eligible: true,
    eligibility_summary: "The local worker can accept execution work.",
    default_queue: "local-default",
    ffmpeg: binaryStatus(),
    ffprobe: binaryStatus(),
    local_worker_queue: "local-default",
    last_run_started_at: "2026-04-20T10:04:30Z",
    last_run_completed_at: "2026-04-20T10:05:00Z",
    last_processed_job_id: "job-1",
    last_result_status: "completed",
    last_failure_message: null,
    processed_jobs: 4,
    current_job_id: null,
    current_backend: null,
    current_stage: null,
    current_progress_percent: null,
    current_progress_updated_at: null,
    telemetry: {
      collected_at: "2026-04-22T12:00:00Z",
      cpu_usage_percent: 21.2,
      process_cpu_usage_percent: 5.4,
      memory_usage_percent: 33.1,
      process_memory_bytes: 104857600,
      cpu_temperature_c: null,
      gpu: null,
    },
    capabilities: { ffmpeg: true, ffprobe: true, intel_qsv: false },
    execution_backends: ["remux", "transcode"],
    hardware_acceleration: [],
    hardware_probes: executionBackendStatuses(),
    runtime_device_paths: runtimeDevicePaths(),
    execution_preferences: executionPreferences(),
    scratch_path: pathStatus({
      role: "scratch",
      display_name: "Scratch workspace",
      path: "/temp",
      status: "healthy",
      writable: true,
    }),
    media_paths: [
      pathStatus({
        role: "media_mount",
        display_name: "Media library",
        path: "/media",
        status: "healthy",
        writable: true,
      }),
    ],
    queue_health: queueHealth(),
    self_test_available: true,
    ...overrides,
  };
}

function binaryStatus() {
  return {
    configured_path: "/usr/bin/ffmpeg",
    discoverable: true,
    exists: true,
    executable: true,
    status: "healthy",
    message: "Binary is discoverable and executable.",
  };
}

function queueHealth() {
  return {
    status: "healthy",
    summary: "Queue health is within expected bounds.",
    pending_count: 1,
    running_count: 0,
    failed_count: 1,
    manual_review_count: 1,
    completed_count: 4,
    oldest_pending_age_seconds: 3600,
    last_completed_age_seconds: 300,
    recent_failed_count: 1,
    recent_manual_review_count: 1,
  };
}

function runtimeStatus() {
  return {
    status: "healthy",
    summary: "Runtime health is healthy.",
    version: CURRENT_VERSION,
    environment: "production",
    db_reachable: true,
    schema_reachable: true,
    auth_enabled: true,
    api_base_path: "/api",
    standard_media_root: "/media",
    scratch_dir: "/temp",
    data_dir: "/data",
    media_mounts: ["/media"],
    local_worker_enabled: true,
    first_user_setup_required: false,
    storage_setup_incomplete: false,
    user_count: 1,
    config_sources: {
      app: "/opt/encodr/config/app.yaml",
      policy: "/opt/encodr/config/policy.yaml",
      workers: "/opt/encodr/config/workers.yaml",
    },
    warnings: [],
    execution_backends: executionBackendStatuses(),
    runtime_device_paths: runtimeDevicePaths(),
    execution_preferences: executionPreferences(),
    queue_health: queueHealth(),
  };
}

function updateStatus() {
  return {
    current_version: CURRENT_VERSION,
    latest_version: CURRENT_VERSION,
    update_available: false,
    channel: "internal",
    status: "ok",
    release_name: `Encodr v${CURRENT_VERSION}`,
    release_summary: "Current release installed.",
    breaking_changes_summary: null,
    checked_at: "2026-04-21T08:00:00Z",
    error: null,
    download_url: null,
    release_notes_url: null,
  };
}

function executionPreferences() {
  return {
    preferred_backend: "cpu_only",
    allow_cpu_fallback: true,
  };
}

function runtimeDevicePaths() {
  return [
    {
      path: "/dev/dri/card1",
      exists: true,
      readable: true,
      writable: true,
      is_character_device: true,
      status: "healthy",
      message: "Device path is present and readable.",
      vendor_id: "0x8086",
      vendor_name: "Intel",
    },
    {
      path: "/dev/dri/renderD128",
      exists: true,
      readable: true,
      writable: true,
      is_character_device: true,
      status: "healthy",
      message: "Device path is present and readable.",
      vendor_id: "0x8086",
      vendor_name: "Intel",
    },
  ];
}

function executionBackendStatuses() {
  return [
    {
      backend: "cpu",
      preference_key: "cpu_only",
      detected: true,
      usable_by_ffmpeg: true,
      ffmpeg_path_verified: true,
      status: "healthy",
      message: "CPU execution is available.",
      reason_unavailable: null,
      recommended_usage: "Use CPU execution as the safe fallback on any host.",
      device_paths: [],
      details: {},
    },
    {
      backend: "intel_igpu",
      preference_key: "prefer_intel_igpu",
      detected: true,
      usable_by_ffmpeg: false,
      ffmpeg_path_verified: false,
      status: "failed",
      message: "Intel iGPU passthrough is not fully usable in this runtime.",
      reason_unavailable: "Intel driver missing",
      recommended_usage: "Expose /dev/dri to the worker runtime and validate Intel VAAPI before selecting Intel iGPU.",
      device_paths: runtimeDevicePaths(),
      details: {
        qsv: {
          usable: false,
          status: "unknown",
          message: "Intel QSV is visible in FFmpeg but remains unverified in this runtime.",
        },
        vaapi: {
          usable: false,
          message: "Intel VAAPI userspace driver is missing or could not be loaded.",
          reason_unavailable: "Intel driver missing",
        },
      },
    },
    {
      backend: "nvidia_gpu",
      preference_key: "prefer_nvidia_gpu",
      detected: false,
      usable_by_ffmpeg: false,
      ffmpeg_path_verified: false,
      status: "failed",
      message: "No NVIDIA runtime device is visible to the runtime.",
      reason_unavailable: "No NVIDIA runtime device is visible to the runtime.",
      recommended_usage: "Expose /dev/nvidia* devices and the NVIDIA container runtime before selecting this backend.",
      device_paths: [],
      details: {},
    },
    {
      backend: "amd_gpu",
      preference_key: "prefer_amd_gpu",
      detected: false,
      usable_by_ffmpeg: false,
      ffmpeg_path_verified: false,
      status: "failed",
      message: "AMD GPU passthrough is not fully usable by FFmpeg.",
      reason_unavailable: "AMD render device is not visible to the runtime.",
      recommended_usage: "Expose the AMD /dev/dri render device and verify VAAPI support before selecting this backend.",
      device_paths: [],
      details: {},
    },
  ];
}

function storageStatus() {
  return {
    status: "healthy",
    summary: "Configured storage paths are healthy.",
    standard_media_root: "/media",
    scratch: pathStatus({
      role: "scratch",
      display_name: "Scratch workspace",
      path: "/temp",
      status: "healthy",
      writable: true,
    }),
    data_dir: pathStatus({
      role: "data",
      display_name: "Application data",
      path: "/data",
      status: "healthy",
      writable: true,
    }),
    media_mounts: [
      pathStatus({
        role: "media",
        display_name: "Media library",
        path: "/media",
        status: "healthy",
        writable: true,
      }),
    ],
    warnings: [],
  };
}

function effectiveConfig() {
  return {
    app_name: "Encodr",
    environment: "production",
    timezone: "Europe/London",
    scratch_dir: "/temp",
    data_dir: "/data",
    output: {
      return_to_original_folder: true,
      default_container: "mkv",
    },
    auth: {
      enabled: true,
      session_mode: "jwt",
      access_token_ttl_minutes: 30,
      refresh_token_ttl_days: 14,
      access_token_algorithm: "HS256",
    },
    policy_version: 1,
    policy_name: "default",
    profile_names: ["Movies", "TV"],
    audio: {
      keep_languages: ["eng"],
      preserve_best_surround: true,
      preserve_atmos_capable: true,
      preferred_codecs: ["aac", "ac3"],
      allow_commentary: false,
      max_tracks_to_keep: 2,
    },
    subtitles: {
      keep_languages: ["eng"],
      keep_forced_languages: ["eng"],
      keep_commentary: false,
      keep_hearing_impaired: false,
    },
    video: {
      output_container: "mkv",
      non_4k_preferred_codec: "hevc",
      non_4k_allow_transcode: true,
      non_4k_max_video_bitrate_mbps: 18,
      non_4k_max_width: 1920,
      four_k_mode: "preserve",
      four_k_preserve_original_video: true,
      four_k_remove_non_english_audio: true,
      four_k_remove_non_english_subtitles: true,
    },
    workers: [],
    profiles: [
      { name: "Movies", description: null, source_path: "/config/profiles/movies.yaml", path_prefixes: ["/media/Movies"] },
      { name: "TV", description: null, source_path: "/config/profiles/tv.yaml", path_prefixes: ["/media/TV"] },
    ],
    sources: {
      app: {
        requested_path: "/config/app.yaml",
        resolved_path: "/config/app.yaml",
        used_example_fallback: false,
        from_environment: false,
      },
    },
  };
}

function processingRules() {
  return {
    movies: processingRuleset({ profile_name: "movies-default" }),
    movies_4k: processingRuleset({
      profile_name: "movies-4k-default",
      current: {
        ...processingRuleValues(),
        handling_mode: "preserve_video",
        max_allowed_video_reduction_percent: 20,
      },
    }),
    tv: processingRuleset({
      profile_name: "tv-default",
      current: {
        ...processingRuleValues(),
        target_quality_mode: "balanced",
        max_allowed_video_reduction_percent: 30,
      },
    }),
    tv_4k: processingRuleset({
      profile_name: "tv-4k-default",
      current: {
        ...processingRuleValues(),
        handling_mode: "strip_only",
        max_allowed_video_reduction_percent: 15,
      },
    }),
  };
}

function processingRuleset({
  profile_name,
  uses_defaults = true,
  current = processingRuleValues(),
  defaults = current,
}: {
  profile_name: string;
  uses_defaults?: boolean;
  current?: ReturnType<typeof processingRuleValues>;
  defaults?: ReturnType<typeof processingRuleValues>;
}) {
  return {
    profile_name,
    uses_defaults,
    current,
    defaults,
  };
}

function processingRuleValues() {
  return {
    target_video_codec: "hevc",
    output_container: "mkv",
    preferred_audio_languages: ["eng"],
    keep_only_preferred_audio_languages: true,
    keep_forced_subtitles: true,
    keep_one_full_preferred_subtitle: true,
    drop_other_subtitles: true,
    preserve_surround: true,
    preserve_seven_one: true,
    preserve_atmos: true,
    preferred_subtitle_languages: ["eng"],
    handling_mode: "transcode",
    target_quality_mode: "high_quality",
    max_allowed_video_reduction_percent: 35,
  };
}

function pathStatus({
  role,
  display_name,
  path,
  status,
  writable,
}: {
  role: string;
  display_name: string;
  path: string;
  status: string;
  writable: boolean;
}) {
  return {
    role,
    display_name,
    path,
    status,
    issue_code: "ok",
    message: `${display_name} is available.`,
    recommended_action: null,
    exists: true,
    is_directory: true,
    is_mount: true,
    readable: true,
    writable,
    same_filesystem_as_root: false,
    entry_count: 4,
    total_space_bytes: 1000,
    free_space_bytes: 500,
    free_space_ratio: 0.5,
  };
}

function jobDetail() {
  return {
    id: "job-1",
    tracked_file_id: "file-1",
    plan_snapshot_id: "plan-1",
    source_path: "/media/Movies/Example Film (2024).mkv",
    source_filename: "Example Film (2024).mkv",
    worker_name: "worker-local",
    status: "pending",
    attempt_count: 1,
    started_at: null,
    completed_at: null,
    progress_stage: null,
    progress_percent: null,
    progress_out_time_seconds: null,
    progress_fps: null,
    progress_speed: null,
    progress_updated_at: null,
    requested_execution_backend: "cpu",
    actual_execution_backend: null,
    actual_execution_accelerator: null,
    backend_fallback_used: false,
    backend_selection_reason: null,
    failure_message: null,
    failure_category: null,
    verification_status: "pending",
    replacement_status: "pending",
    tracked_file_is_protected: false,
    requires_review: false,
    review_status: null,
    input_size_bytes: null,
    output_size_bytes: null,
    space_saved_bytes: null,
    video_input_size_bytes: null,
    video_output_size_bytes: null,
    video_space_saved_bytes: null,
    non_video_space_saved_bytes: null,
    compression_reduction_percent: null,
    assigned_worker_id: null,
    last_worker_id: null,
    preferred_worker_id: null,
    pinned_worker_id: null,
    preferred_backend_override: null,
    schedule_windows: [],
    schedule_summary: null,
    scheduled_for_at: null,
    interrupted_at: null,
    interruption_reason: null,
    interruption_retryable: true,
    watched_job_id: null,
    requested_worker_type: null,
    created_at: "2026-04-20T10:02:30Z",
    updated_at: "2026-04-20T10:02:30Z",
    output_path: null,
    final_output_path: null,
    original_backup_path: null,
    execution_command: null,
    execution_stdout: null,
    execution_stderr: null,
    verification_payload: null,
    replacement_payload: null,
    replacement_failure_message: null,
    replace_in_place: true,
    require_verification: true,
    keep_original_until_verified: true,
    delete_replaced_source: false,
  };
}

function reviewItemDetail() {
  return {
    id: "item-1",
    source_path: "/media/Movies/Example Film (2024).mkv",
    review_status: "open",
    requires_review: true,
    confidence: "low",
    tracked_file: {
      id: "file-1",
      source_path: "/media/Movies/Example Film (2024).mkv",
      source_filename: "Example Film (2024).mkv",
      source_extension: ".mkv",
      source_directory: "/media/Movies",
      last_observed_size: 100,
      last_observed_modified_time: "2026-04-20T10:00:00Z",
      fingerprint_placeholder: null,
      is_4k: false,
      lifecycle_state: "manual_review",
      compliance_state: "manual_review",
      is_protected: true,
      operator_protected: false,
      protected_source: "planner",
      operator_protected_note: null,
      requires_review: true,
      review_status: "open",
      last_processed_policy_version: 1,
      last_processed_profile_name: "default",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:00:00Z",
    },
    latest_plan: {
      id: "plan-1",
      tracked_file_id: "file-1",
      probe_snapshot_id: "probe-1",
      action: "manual_review",
      confidence: "low",
      policy_version: 1,
      profile_name: "default",
      is_already_compliant: false,
      should_treat_as_protected: true,
      created_at: "2026-04-20T10:01:00Z",
      reason_codes: ["manual_review_missing_english_audio"],
      warning_codes: ["video_transcode_required_for_policy_codec"],
      selected_audio_stream_indices: [],
      selected_subtitle_stream_indices: [],
    },
    latest_job: {
      ...jobDetail(),
      id: "job-1",
      status: "failed",
      verification_status: "failed",
      replacement_status: "pending",
      failure_message: "Verification failed",
    },
    protected_state: {
      is_protected: true,
      planner_protected: true,
      operator_protected: false,
      source: "planner",
      reason_codes: ["manual_review_missing_english_audio"],
      note: null,
      updated_at: "2026-04-20T10:02:00Z",
      updated_by_username: "admin",
    },
    reasons: [
      { code: "manual_review_missing_english_audio", message: "Missing English audio", kind: "reason" },
    ],
    warnings: [
      { code: "video_transcode_required_for_policy_codec", message: "Video transcode required", kind: "warning" },
    ],
    latest_probe_at: "2026-04-20T10:00:30Z",
    latest_plan_at: "2026-04-20T10:01:00Z",
    latest_job_at: "2026-04-20T10:02:30Z",
    latest_decision: null,
    latest_probe_snapshot_id: "probe-1",
    latest_plan_snapshot_id: "plan-1",
    latest_job_id: "job-1",
  };
}

function workerInventory() {
  return {
    id: "worker-local-1",
    worker_key: "local",
    display_name: "Local worker",
    worker_type: "local",
    worker_state: "local_healthy",
    source: "configured_local",
    enabled: true,
    registration_status: "registered",
    health_status: "healthy",
    health_summary: "Healthy",
    last_seen_at: "2026-04-20T10:05:00Z",
    last_heartbeat_at: "2026-04-20T10:05:00Z",
    last_registration_at: "2026-04-20T10:00:00Z",
    preferred_backend: "cpu_only",
    allow_cpu_fallback: true,
    current_job_id: null,
    current_backend: null,
    current_stage: null,
    current_progress_percent: null,
    onboarding_platform: null,
    pairing_expires_at: null,
    capability_summary: {
      execution_modes: ["local"],
      supported_video_codecs: ["hevc"],
      supported_audio_codecs: ["aac"],
      hardware_hints: [],
      binary_support: { ffmpeg: true },
      max_concurrent_jobs: 1,
      tags: [],
    },
    host_summary: {
      hostname: "encodr",
      platform: "linux",
      agent_version: CURRENT_VERSION,
      python_version: "3.12",
    },
    pending_assignment_count: 0,
    last_completed_job_id: null,
    runtime_summary: {
      queue: "remote-default",
      scratch_dir: "/temp",
      media_mounts: ["/media"],
      preferred_backend: "cpu",
      allow_cpu_fallback: true,
      schedule_windows: [],
      current_job_id: null,
      current_backend: null,
      current_stage: null,
      current_progress_percent: null,
      current_progress_updated_at: null,
      telemetry: null,
      last_completed_job_id: null,
    },
    schedule_windows: [],
    schedule_summary: null,
    binary_summary: [],
    assigned_job_ids: [],
    last_processed_job_id: null,
    recent_failure_message: null,
    recent_jobs: [],
  };
}
