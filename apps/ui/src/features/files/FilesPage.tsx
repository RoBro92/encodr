import { useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { FolderPickerModal } from "../../components/FolderPickerModal";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { ScheduleWindowsEditor } from "../../components/ScheduleWindowsEditor";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useBatchPlanMutation,
  useCreateBatchJobsMutation,
  useCreateWatchedJobMutation,
  useDryRunMutation,
  useLibraryRootsQuery,
  useScanFolderMutation,
  useScansQuery,
  useUpdateWatchedJobMutation,
  useWatchedJobsQuery,
  useWorkersQuery,
} from "../../lib/api/hooks";
import type { FolderScanSummary, WatchedJob, WatchedJobPayload } from "../../lib/types/api";
import { formatDateTime, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

type LibraryTab = "browse" | "scan" | "dry-run" | "batch-plan";

type WatcherDraft = WatchedJobPayload & {
  id?: string;
};

const MEDIA_CLASS_OPTIONS = [
  { value: "movie", label: "Movies" },
  { value: "movie_4k", label: "Movies 4K" },
  { value: "tv", label: "TV" },
  { value: "tv_4k", label: "TV 4K" },
  { value: "mixed", label: "Mixed" },
];

const RULESET_OPTIONS = [
  { value: "", label: "Use inferred ruleset" },
  { value: "movies", label: "Movies" },
  { value: "movies_4k", label: "Movies 4K" },
  { value: "tv", label: "TV" },
  { value: "tv_4k", label: "TV 4K" },
];

const BACKEND_OPTIONS = [
  { value: "", label: "Use worker default" },
  { value: "cpu_only", label: "CPU only" },
  { value: "prefer_intel_igpu", label: "Prefer Intel iGPU" },
  { value: "prefer_nvidia_gpu", label: "Prefer NVIDIA" },
  { value: "prefer_amd_gpu", label: "Prefer AMD" },
];

function inferWatcherDefaults(path: string | null, moviesRoot: string | null, tvRoot: string | null): WatcherDraft {
  const normalised = (path ?? "").toLowerCase();
  const underMovies = Boolean(moviesRoot && path?.startsWith(moviesRoot));
  const underTv = Boolean(tvRoot && path?.startsWith(tvRoot));
  const looks4k = /(^|\/)(4k|uhd)(\/|$)/i.test(normalised);
  let mediaClass = "mixed";
  let ruleset = "";

  if (underMovies) {
    mediaClass = looks4k ? "movie_4k" : "movie";
    ruleset = looks4k ? "movies_4k" : "movies";
  } else if (underTv) {
    mediaClass = looks4k ? "tv_4k" : "tv";
    ruleset = looks4k ? "tv_4k" : "tv";
  }

  return {
    display_name: path ? path.split("/").filter(Boolean).at(-1) ?? "Watched folder" : "Watched folder",
    source_path: path ?? "",
    media_class: mediaClass,
    ruleset_override: ruleset || undefined,
    preferred_worker_id: undefined,
    pinned_worker_id: undefined,
    preferred_backend: undefined,
    schedule_windows: [],
    auto_queue: true,
    stage_only: false,
    enabled: true,
  };
}

function watcherDraftFromRecord(item: WatchedJob): WatcherDraft {
  return {
    id: item.id,
    display_name: item.display_name,
    source_path: item.source_path,
    media_class: item.media_class,
    ruleset_override: item.ruleset_override ?? undefined,
    preferred_worker_id: item.preferred_worker_id ?? undefined,
    pinned_worker_id: item.pinned_worker_id ?? undefined,
    preferred_backend: item.preferred_backend ?? undefined,
    schedule_windows: item.schedule_windows,
    auto_queue: item.auto_queue,
    stage_only: item.stage_only,
    enabled: item.enabled,
  };
}

export function FilesPage() {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<LibraryTab>("browse");
  const [activeScanDraft, setActiveScanDraft] = useState<FolderScanSummary | null>(null);
  const [watcherDraft, setWatcherDraft] = useState<WatcherDraft | null>(null);

  const rootsQuery = useLibraryRootsQuery();
  const scansQuery = useScansQuery();
  const watchedJobsQuery = useWatchedJobsQuery();
  const workersQuery = useWorkersQuery();
  const scanMutation = useScanFolderMutation();
  const dryRunMutation = useDryRunMutation();
  const batchPlanMutation = useBatchPlanMutation();
  const batchJobsMutation = useCreateBatchJobsMutation();
  const createWatchedJobMutation = useCreateWatchedJobMutation();
  const updateWatchedJobMutation = useUpdateWatchedJobMutation();

  const loading = rootsQuery.isLoading || scansQuery.isLoading || watchedJobsQuery.isLoading || workersQuery.isLoading;
  if (loading) {
    return <LoadingBlock label="Loading library" />;
  }

  const error = rootsQuery.error ?? scansQuery.error ?? watchedJobsQuery.error ?? workersQuery.error;
  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load the library" message={error.message} />;
  }

  const roots = rootsQuery.data;
  if (!roots) {
    return <ErrorPanel title="Library is unavailable" message="The API did not return library roots." />;
  }

  const recentScans = scansQuery.data?.items ?? [];
  const watchedJobs = watchedJobsQuery.data?.items ?? [];
  const workers = workersQuery.data?.items ?? [];
  const moviesRoot = roots.movies_root;
  const tvRoot = roots.tv_root;
  const activeScan = activeScanDraft
    ? activeScanDraft.scan_id
      ? recentScans.find((item) => item.scan_id === activeScanDraft.scan_id) ?? activeScanDraft
      : activeScanDraft
    : null;

  const selectedSet = new Set(selectedPaths);
  const allSelected = Boolean(activeScan && activeScan.files.length > 0 && selectedPaths.length === activeScan.files.length);
  const hasSavedRoots = Boolean(roots.movies_root || roots.tv_root);
  const activeSelection =
    selectedPaths.length > 0
      ? { selected_paths: selectedPaths }
      : selectedFolder
        ? { folder_path: selectedFolder }
        : undefined;
  const showWorkspaceTabs = Boolean(selectedFolder);
  const currentTab = showWorkspaceTabs ? activeTab : "browse";
  const selectedCount = selectedPaths.length;
  const selectedCountLabel =
    selectedCount === 1 ? "1 file selected" : `${selectedCount} files selected`;
  const selectionScopeLabel =
    selectedPaths.length > 0
      ? `${selectedPaths.length} file${selectedPaths.length === 1 ? "" : "s"} selected`
      : selectedFolder
        ? "Entire folder selected"
        : "No folder selected";
  const selectionScopeCopy =
    selectedPaths.length > 0
      ? "Dry run, plan, or create jobs for the selected files."
      : selectedFolder
        ? "Dry run, plan, or create jobs for the whole folder."
        : "Choose a folder to begin.";

  const workerOptions = workers.map((worker) => ({
    id: worker.id,
    label: `${worker.display_name} (${worker.worker_type === "local" ? "local" : "remote"})`,
  }));

  function togglePath(path: string) {
    setSelectedPaths((current) =>
      current.includes(path) ? current.filter((item) => item !== path) : [...current, path],
    );
  }

  function selectAllVisible() {
    if (!activeScan) {
      return;
    }
    setSelectedPaths(activeScan.files.map((item) => item.path));
  }

  function clearSelection() {
    setSelectedPaths([]);
  }

  async function runScan(path: string) {
    setSelectedFolder(path);
    setSelectedPaths([]);
    setActiveTab("scan");
    const result = await scanMutation.mutateAsync({ source_path: path });
    setActiveScanDraft(result);
  }

  function openSavedScan(scan: FolderScanSummary) {
    setSelectedFolder(scan.folder_path);
    setSelectedPaths([]);
    setActiveTab("scan");
    setActiveScanDraft(scan);
  }

  function openWatcherDraft(item?: WatchedJob) {
    if (item) {
      setWatcherDraft(watcherDraftFromRecord(item));
      return;
    }
    setWatcherDraft(inferWatcherDefaults(selectedFolder, moviesRoot, tvRoot));
  }

  async function saveWatcher() {
    if (!watcherDraft) {
      return;
    }
    const payload: WatchedJobPayload = {
      display_name: watcherDraft.display_name,
      source_path: watcherDraft.source_path,
      media_class: watcherDraft.media_class,
      ruleset_override: watcherDraft.ruleset_override,
      preferred_worker_id: watcherDraft.preferred_worker_id,
      pinned_worker_id: watcherDraft.pinned_worker_id,
      preferred_backend: watcherDraft.preferred_backend,
      schedule_windows: watcherDraft.schedule_windows,
      auto_queue: watcherDraft.auto_queue,
      stage_only: watcherDraft.stage_only,
      enabled: watcherDraft.enabled,
    };
    if (watcherDraft.id) {
      await updateWatchedJobMutation.mutateAsync({ watchedJobId: watcherDraft.id, payload });
    } else {
      await createWatchedJobMutation.mutateAsync(payload);
    }
    setWatcherDraft(null);
  }

  function runDryRun() {
    if (!activeSelection) {
      return;
    }
    setActiveTab("dry-run");
    dryRunMutation.mutate(activeSelection);
  }

  function runBatchPlan() {
    if (!activeSelection) {
      return;
    }
    setActiveTab("batch-plan");
    batchPlanMutation.mutate(activeSelection);
  }

  function runBatchJobs() {
    if (!activeSelection) {
      return;
    }
    setActiveTab("batch-plan");
    batchJobsMutation.mutate(activeSelection);
  }

  const tabs: Array<{ key: LibraryTab; label: string }> = [
    { key: "browse", label: "Browse" },
    { key: "scan", label: "Scan Results" },
    { key: "dry-run", label: "Dry Run" },
    { key: "batch-plan", label: "Batch Plan" },
  ];

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Library"
        title="Library"
        description="Choose a folder, scan it, inspect the files, then dry run or create jobs."
        actions={
          <div className="page-actions">
            <button className="button button-secondary" type="button" onClick={() => setPickerOpen(true)}>
              Browse folders
            </button>
            {selectedFolder ? (
              <>
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => void runScan(selectedFolder)}
                  disabled={scanMutation.isPending}
                >
                  {scanMutation.isPending ? "Scanning…" : "Scan folder"}
                </button>
                <button className="button button-primary" type="button" onClick={() => openWatcherDraft()}>
                  Watch folder
                </button>
              </>
            ) : null}
          </div>
        }
      />

      {scanMutation.error instanceof Error ? (
        <ErrorPanel title="Scan failed" message={scanMutation.error.message} />
      ) : null}
      {dryRunMutation.error instanceof Error ? (
        <ErrorPanel title="Dry run failed" message={dryRunMutation.error.message} />
      ) : null}
      {batchPlanMutation.error instanceof Error ? (
        <ErrorPanel title="Batch plan failed" message={batchPlanMutation.error.message} />
      ) : null}
      {batchJobsMutation.error instanceof Error ? (
        <ErrorPanel title="Batch job creation failed" message={batchJobsMutation.error.message} />
      ) : null}
      {createWatchedJobMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to create watched job" message={createWatchedJobMutation.error.message} />
      ) : null}
      {updateWatchedJobMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to update watched job" message={updateWatchedJobMutation.error.message} />
      ) : null}

      {!hasSavedRoots ? (
        <div className="info-strip" role="note">
          <strong>Library roots not set.</strong>
          <span>
            Choose your Movies and TV folders in <Link className="text-link" to={APP_ROUTES.config}>Settings</Link>.
          </span>
        </div>
      ) : null}

      <SectionCard
        title="Current folder"
        subtitle={selectedFolder ?? "Choose a folder to browse and scan."}
      >
        <div className="library-header-card">
          <div className="library-header-roots">
            <div className="library-root-card">
              <span className="library-root-label">Movies root</span>
              <strong>{roots.movies_root ?? "Not set"}</strong>
              <div className="library-root-actions">
                {moviesRoot ? (
                  <button className="button button-secondary button-small" type="button" onClick={() => void runScan(moviesRoot)}>
                    Open
                  </button>
                ) : (
                  <Link className="button button-secondary button-small" to={APP_ROUTES.config}>
                    Set in Settings
                  </Link>
                )}
              </div>
            </div>

            <div className="library-root-card">
              <span className="library-root-label">TV root</span>
              <strong>{roots.tv_root ?? "Not set"}</strong>
              <div className="library-root-actions">
                {tvRoot ? (
                  <button className="button button-secondary button-small" type="button" onClick={() => void runScan(tvRoot)}>
                    Open
                  </button>
                ) : (
                  <Link className="button button-secondary button-small" to={APP_ROUTES.config}>
                    Set in Settings
                  </Link>
                )}
              </div>
            </div>
          </div>

          <div className="library-header-summary">
            <div className="library-header-copy">
              <div className="badge-row">
                <StatusBadge value={selectedFolder ? "selected" : "pending"} />
                <span className="muted-copy">{selectionScopeLabel}</span>
                {activeScan?.scanned_at ? <span className="muted-copy">Scanned {formatDateTime(activeScan.scanned_at)}</span> : null}
              </div>
              <strong className="library-path-copy">{selectedFolder ?? "No folder selected"}</strong>
              <p className="muted-copy">{selectionScopeCopy}</p>
            </div>

            <div className="library-header-metrics">
              <div className="metric-pill">
                <span className="metric-label">Selected</span>
                <strong>{selectedCount}</strong>
              </div>
              {activeScan?.folder_path === selectedFolder ? (
                <>
                  <div className="metric-pill">
                    <span className="metric-label">Video files</span>
                    <strong>{activeScan.video_file_count}</strong>
                  </div>
                  <div className="metric-pill">
                    <span className="metric-label">Likely films</span>
                    <strong>{activeScan.likely_film_count}</strong>
                  </div>
                  <div className="metric-pill">
                    <span className="metric-label">Likely episodes</span>
                    <strong>{activeScan.likely_episode_count}</strong>
                  </div>
                </>
              ) : null}
            </div>

            <div className="library-action-buttons">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => selectedFolder && void runScan(selectedFolder)}
                disabled={!selectedFolder || scanMutation.isPending}
              >
                {scanMutation.isPending ? "Scanning…" : "Scan folder"}
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={runDryRun}
                disabled={!activeSelection || dryRunMutation.isPending}
              >
                {dryRunMutation.isPending ? "Running…" : "Dry Run"}
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={runBatchPlan}
                disabled={!activeSelection || batchPlanMutation.isPending}
              >
                {batchPlanMutation.isPending ? "Planning…" : "Batch Plan"}
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={runBatchJobs}
                disabled={!activeSelection || batchJobsMutation.isPending}
              >
                {batchJobsMutation.isPending ? "Creating…" : "Create Jobs"}
              </button>
            </div>
          </div>
        </div>
      </SectionCard>

      <div className="dashboard-grid">
        <SectionCard
          title="Recent scans"
          subtitle="Reopen saved scan results or rescan a folder when it changes."
        >
          {recentScans.length === 0 ? (
            <EmptyState title="No saved scans yet" message="Run a folder scan to keep the result available for later job creation." />
          ) : (
            <div className="list-stack">
              {recentScans.map((scan) => (
                <div key={scan.scan_id ?? scan.folder_path} className="list-row">
                  <div>
                    <strong>{scan.folder_path}</strong>
                    <p>
                      {scan.video_file_count} file{scan.video_file_count === 1 ? "" : "s"} • {scan.source_kind === "watched" ? "Watched" : "Manual"} • {formatDateTime(scan.scanned_at)}
                    </p>
                    {scan.stale ? <p>Saved result may be stale.</p> : null}
                  </div>
                  <div className="list-row-meta">
                    {scan.stale ? <StatusBadge value="stale" /> : <StatusBadge value="saved" />}
                    <button className="button button-secondary button-small" type="button" onClick={() => openSavedScan(scan)}>
                      Reopen
                    </button>
                    <button className="button button-secondary button-small" type="button" onClick={() => void runScan(scan.folder_path)}>
                      Rescan
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard
          title="Watched folders"
          subtitle="Queue or stage new files automatically from SSD or library folders."
          actions={
            <button className="button button-primary button-small" type="button" onClick={() => openWatcherDraft()}>
              Add watched job
            </button>
          }
        >
          <div className="card-stack">
            {watcherDraft ? (
              <div className="settings-rules-fields settings-rules-fields-compact">
                <label className="field">
                  <span>Name</span>
                  <input
                    aria-label="Watched job name"
                    value={watcherDraft.display_name}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, display_name: event.target.value } : current)}
                  />
                </label>
                <label className="field">
                  <span>Source path</span>
                  <input
                    aria-label="Watched source path"
                    value={watcherDraft.source_path}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, source_path: event.target.value } : current)}
                  />
                </label>
                <label className="field">
                  <span>Media class</span>
                  <select
                    aria-label="Watched media class"
                    value={watcherDraft.media_class}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, media_class: event.target.value } : current)}
                  >
                    {MEDIA_CLASS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Ruleset</span>
                  <select
                    aria-label="Watched ruleset"
                    value={watcherDraft.ruleset_override ?? ""}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, ruleset_override: event.target.value || undefined } : current)}
                  >
                    {RULESET_OPTIONS.map((option) => (
                      <option key={option.value || "inferred"} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Preferred worker</span>
                  <select
                    aria-label="Watched preferred worker"
                    value={watcherDraft.preferred_worker_id ?? ""}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, preferred_worker_id: event.target.value || undefined } : current)}
                  >
                    <option value="">Automatic</option>
                    {workerOptions.map((worker) => (
                      <option key={worker.id} value={worker.id}>{worker.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Pinned worker</span>
                  <select
                    aria-label="Watched pinned worker"
                    value={watcherDraft.pinned_worker_id ?? ""}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, pinned_worker_id: event.target.value || undefined } : current)}
                  >
                    <option value="">No pin</option>
                    {workerOptions.map((worker) => (
                      <option key={worker.id} value={worker.id}>{worker.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Preferred backend</span>
                  <select
                    aria-label="Watched preferred backend"
                    value={watcherDraft.preferred_backend ?? ""}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, preferred_backend: event.target.value || undefined } : current)}
                  >
                    {BACKEND_OPTIONS.map((option) => (
                      <option key={option.value || "default"} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>

                <ScheduleWindowsEditor
                  label="Schedule windows"
                  value={watcherDraft.schedule_windows ?? []}
                  onChange={(value) => setWatcherDraft((current) => current ? { ...current, schedule_windows: value } : current)}
                />

                <label className="field field-checkbox">
                  <span>Auto queue new files</span>
                  <input
                    aria-label="Watched auto queue"
                    type="checkbox"
                    checked={watcherDraft.auto_queue}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, auto_queue: event.target.checked } : current)}
                  />
                </label>
                <label className="field field-checkbox">
                  <span>Stage only</span>
                  <input
                    aria-label="Watched stage only"
                    type="checkbox"
                    checked={watcherDraft.stage_only}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, stage_only: event.target.checked } : current)}
                  />
                </label>
                <label className="field field-checkbox">
                  <span>Enabled</span>
                  <input
                    aria-label="Watched enabled"
                    type="checkbox"
                    checked={watcherDraft.enabled}
                    onChange={(event) => setWatcherDraft((current) => current ? { ...current, enabled: event.target.checked } : current)}
                  />
                </label>

                <div className="section-card-actions">
                  <button
                    className="button button-primary button-small"
                    type="button"
                    onClick={() => void saveWatcher()}
                    disabled={createWatchedJobMutation.isPending || updateWatchedJobMutation.isPending}
                  >
                    {createWatchedJobMutation.isPending || updateWatchedJobMutation.isPending
                      ? "Saving…"
                      : watcherDraft.id ? "Save watched job" : "Create watched job"}
                  </button>
                  <button className="button button-secondary button-small" type="button" onClick={() => setWatcherDraft(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}

            {watchedJobs.length === 0 ? (
              <EmptyState title="No watched folders yet" message="Create a watched job to queue or stage new files automatically from an SSD or library path." />
            ) : (
              <div className="list-stack">
                {watchedJobs.map((item) => (
                  <div key={item.id} className="list-row">
                    <div>
                      <strong>{item.display_name}</strong>
                      <p>{item.source_path}</p>
                      <p>
                        {mediaClassLabel(item.media_class)}
                        {item.ruleset_override ? ` • ${rulesetLabel(item.ruleset_override)}` : ""}
                        {item.schedule_summary ? ` • ${item.schedule_summary}` : ""}
                      </p>
                      <p>
                        {item.auto_queue && !item.stage_only ? "Auto queue" : "Stage only"}
                        {item.last_scan_at ? ` • Last scan ${formatDateTime(item.last_scan_at)}` : ""}
                        {item.last_seen_count ? ` • ${item.last_seen_count} known file${item.last_seen_count === 1 ? "" : "s"}` : ""}
                      </p>
                    </div>
                    <div className="list-row-meta">
                      <StatusBadge value={item.enabled ? "enabled" : "disabled"} />
                      <button className="button button-secondary button-small" type="button" onClick={() => openWatcherDraft(item)}>
                        Edit
                      </button>
                      <button className="button button-secondary button-small" type="button" onClick={() => void runScan(item.source_path)}>
                        Scan now
                      </button>
                      <button
                        className="button button-secondary button-small"
                        type="button"
                        onClick={() => {
                          void updateWatchedJobMutation.mutateAsync({
                            watchedJobId: item.id,
                            payload: {
                              display_name: item.display_name,
                              source_path: item.source_path,
                              media_class: item.media_class,
                              ruleset_override: item.ruleset_override,
                              preferred_worker_id: item.preferred_worker_id,
                              pinned_worker_id: item.pinned_worker_id,
                              preferred_backend: item.preferred_backend,
                              schedule_windows: item.schedule_windows,
                              auto_queue: item.auto_queue,
                              stage_only: item.stage_only,
                              enabled: !item.enabled,
                            },
                          });
                        }}
                        disabled={updateWatchedJobMutation.isPending}
                      >
                        {item.enabled ? "Disable" : "Enable"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </SectionCard>
      </div>

      <SectionCard
        title="Library workspace"
        subtitle={selectedFolder ?? "Choose a folder to browse and scan."}
      >
        {showWorkspaceTabs ? (
          <div className="library-tabs" role="tablist" aria-label="Library views">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                className={`library-tab${currentTab === tab.key ? " library-tab-active" : ""}`}
                role="tab"
                type="button"
                aria-selected={currentTab === tab.key}
                aria-controls={`library-tabpanel-${tab.key}`}
                id={`library-tab-${tab.key}`}
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        ) : null}

        <div
          id={`library-tabpanel-${currentTab}`}
          className="library-tab-panel"
          role="tabpanel"
          aria-labelledby={`library-tab-${currentTab}`}
        >
          {currentTab === "browse" ? (
            <div className="card-stack">
              <div className="library-browser-grid">
                <button
                  className="library-folder-card"
                  type="button"
                  onClick={() => roots.movies_root && void runScan(roots.movies_root)}
                  disabled={!roots.movies_root}
                >
                  <span className="section-eyebrow">Movies</span>
                  <strong>{roots.movies_root ?? "Set in Settings"}</strong>
                </button>
                <button
                  className="library-folder-card"
                  type="button"
                  onClick={() => roots.tv_root && void runScan(roots.tv_root)}
                  disabled={!roots.tv_root}
                >
                  <span className="section-eyebrow">TV</span>
                  <strong>{roots.tv_root ?? "Set in Settings"}</strong>
                </button>
                <button className="library-folder-card library-folder-card-accent" type="button" onClick={() => setPickerOpen(true)}>
                  <span className="section-eyebrow">Browse</span>
                  <strong>Choose another folder</strong>
                </button>
              </div>
            </div>
          ) : null}

          {currentTab === "scan" ? (
            scanMutation.isPending && !activeScan ? (
              <LoadingBlock label="Scanning folder" />
            ) : activeScan ? (
              <div className="card-stack">
                <div className="metric-grid">
                  <div className="metric-panel">
                    <span className="metric-label">Folders</span>
                    <strong>{activeScan.directory_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Video files</span>
                    <strong>{activeScan.video_file_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Likely films</span>
                    <strong>{activeScan.likely_film_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Likely episodes</span>
                    <strong>{activeScan.likely_episode_count}</strong>
                  </div>
                </div>

                <div className="library-selection-toolbar">
                  <div className="library-selection-copy">
                    <strong>{selectedCountLabel}</strong>
                    <span className="muted-copy">
                      {selectedPaths.length > 0 ? "Actions will use the selected files." : "No files selected. Actions will use the folder."}
                    </span>
                  </div>
                  <div className="section-card-actions">
                    <button className="button button-secondary button-small" type="button" onClick={allSelected ? clearSelection : selectAllVisible}>
                      {allSelected ? "Clear selection" : "Select all"}
                    </button>
                    <button className="button button-secondary button-small" type="button" onClick={() => openWatcherDraft()}>
                      Watch this folder
                    </button>
                  </div>
                </div>

                <div className="selection-list">
                  {activeScan.files.map((file) => (
                    <label key={file.path} className={`selection-row${selectedSet.has(file.path) ? " selection-row-active" : ""}`}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${file.name}`}
                        checked={selectedSet.has(file.path)}
                        onChange={() => togglePath(file.path)}
                      />
                      <div>
                        <strong>{file.name}</strong>
                        <p>{file.path}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState title="No scan yet" message="Choose a folder and run a scan to inspect the files." />
            )
          ) : null}

          {currentTab === "dry-run" ? (
            dryRunMutation.data ? (
              <div className="card-stack">
                <div className="info-strip">
                  <strong>Safe preview</strong>
                  <span>Dry Run shows what Encodr would do without creating output files or replacing media.</span>
                </div>
                <div className="metric-grid">
                  <div className="metric-panel">
                    <span className="metric-label">Files</span>
                    <strong>{dryRunMutation.data.total_files}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Review</span>
                    <strong>{dryRunMutation.data.review_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Protected</span>
                    <strong>{dryRunMutation.data.protected_count}</strong>
                  </div>
                </div>
                <div className="badge-list">
                  {dryRunMutation.data.actions.map((item) => (
                    <div key={item.value} className="metric-pill">
                      <StatusBadge value={String(item.value)} />
                      <strong>{item.count}</strong>
                    </div>
                  ))}
                </div>
                <div className="list-stack">
                  {dryRunMutation.data.items.map((item) => (
                    <div key={item.source_path} className="list-row">
                      <div>
                        <strong>{item.file_name}</strong>
                        <p>{item.source_path}</p>
                      </div>
                      <div className="list-row-meta">
                        <StatusBadge value={item.action} />
                        {item.requires_review ? <StatusBadge value="manual_review" /> : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState title="No dry run yet" message="Run Dry Run to preview actions safely before creating jobs." />
            )
          ) : null}

          {currentTab === "batch-plan" ? (
            batchPlanMutation.data || batchJobsMutation.data ? (
              <div className="card-stack">
                {batchPlanMutation.data ? (
                  <div className="card-stack">
                    <div className="info-strip">
                      <strong>Saved plans</strong>
                      <span>These plans were written to Encodr history.</span>
                    </div>
                    <div className="badge-list">
                      {batchPlanMutation.data.actions.map((item) => (
                        <div key={item.value} className="metric-pill">
                          <StatusBadge value={String(item.value)} />
                          <strong>{item.count}</strong>
                        </div>
                      ))}
                    </div>
                    <div className="list-stack">
                      {batchPlanMutation.data.items.map((item) => (
                        <Link key={item.tracked_file.id} className="list-row" to={APP_ROUTES.fileDetail(item.tracked_file.id)}>
                          <div>
                            <strong>{item.tracked_file.source_filename}</strong>
                            <p>{item.tracked_file.source_path}</p>
                          </div>
                          <div className="list-row-meta">
                            <StatusBadge value={item.latest_plan_snapshot.action} />
                            <span>{titleCase(item.latest_plan_snapshot.confidence)}</span>
                          </div>
                        </Link>
                      ))}
                    </div>
                  </div>
                ) : null}

                {batchJobsMutation.data ? (
                  <div className="card-stack">
                    <div className="info-strip">
                      <strong>Jobs created</strong>
                      <span>Blocked items still need review or protection approval.</span>
                    </div>
                    <div className="metric-grid">
                      <div className="metric-panel">
                        <span className="metric-label">Created</span>
                        <strong>{batchJobsMutation.data.created_count}</strong>
                      </div>
                      <div className="metric-panel">
                        <span className="metric-label">Blocked</span>
                        <strong>{batchJobsMutation.data.blocked_count}</strong>
                      </div>
                    </div>
                    <div className="list-stack">
                      {batchJobsMutation.data.items.map((item) => (
                        <div key={item.source_path} className="list-row">
                          <div>
                            <strong>{item.source_path.split("/").pop()}</strong>
                            <p>{item.message ?? item.source_path}</p>
                          </div>
                          <div className="list-row-meta">
                            <StatusBadge value={item.status} />
                            {item.job ? <Link className="text-link" to={APP_ROUTES.jobDetail(item.job.id)}>Open job</Link> : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <EmptyState title="No batch results yet" message="Run Batch Plan or Create Jobs when you are ready to save work." />
            )
          ) : null}
        </div>
      </SectionCard>

      <FolderPickerModal
        open={pickerOpen}
        title="Browse library folders"
        initialPath={selectedFolder ?? roots.movies_root ?? roots.tv_root ?? roots.media_root}
        onClose={() => setPickerOpen(false)}
        onSelect={(path) => {
          setPickerOpen(false);
          void runScan(path);
        }}
      />
    </div>
  );
}

function mediaClassLabel(value: string) {
  return {
    movie: "Movies",
    movie_4k: "Movies 4K",
    tv: "TV",
    tv_4k: "TV 4K",
    mixed: "Mixed",
  }[value] ?? titleCase(value);
}

function rulesetLabel(value: string) {
  return {
    movies: "Movies",
    movies_4k: "Movies 4K",
    tv: "TV",
    tv_4k: "TV 4K",
  }[value] ?? titleCase(value);
}
