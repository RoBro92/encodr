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
  useCreateDryRunJobsMutation,
  useCreateWatchedJobMutation,
  useJobsQuery,
  useLibraryRootsQuery,
  useScanFolderMutation,
  useScansQuery,
  useUpdateWatchedJobMutation,
  useWatchedJobsQuery,
  useWorkersQuery,
} from "../../lib/api/hooks";
import { ApiError } from "../../lib/api/client";
import type { FolderScanSummary, JobSummary, WatchedJob, WatchedJobPayload } from "../../lib/types/api";
import { formatBytes, formatDateTime, titleCase } from "../../lib/utils/format";
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

const DRY_RUN_WARNING_THRESHOLD = 15;

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
  const [dryRunModalOpen, setDryRunModalOpen] = useState(false);
  const [dryRunWorkerId, setDryRunWorkerId] = useState("");
  const [dryRunScheduleConflict, setDryRunScheduleConflict] = useState<{
    worker_id: string;
    worker_name: string;
    schedule_summary: string | null;
  } | null>(null);
  const [latestDryRunJobIds, setLatestDryRunJobIds] = useState<string[]>([]);

  const rootsQuery = useLibraryRootsQuery();
  const scansQuery = useScansQuery();
  const watchedJobsQuery = useWatchedJobsQuery();
  const workersQuery = useWorkersQuery();
  const dryRunJobsQuery = useJobsQuery({ job_kind: "dry_run", limit: 100 });
  const scanMutation = useScanFolderMutation();
  const createDryRunJobsMutation = useCreateDryRunJobsMutation();
  const batchPlanMutation = useBatchPlanMutation();
  const batchJobsMutation = useCreateBatchJobsMutation();
  const createWatchedJobMutation = useCreateWatchedJobMutation();
  const updateWatchedJobMutation = useUpdateWatchedJobMutation();

  const loading =
    rootsQuery.isLoading ||
    scansQuery.isLoading ||
    watchedJobsQuery.isLoading ||
    workersQuery.isLoading ||
    dryRunJobsQuery.isLoading;
  if (loading) {
    return <LoadingBlock label="Loading library" />;
  }

  const error =
    rootsQuery.error ??
    scansQuery.error ??
    watchedJobsQuery.error ??
    workersQuery.error ??
    dryRunJobsQuery.error;
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
  const dryRunJobs = (dryRunJobsQuery.data?.items ?? []).filter((job) => latestDryRunJobIds.includes(job.id));
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
  const dryRunSelectionCount =
    selectedPaths.length > 0
      ? selectedPaths.length
      : activeScan?.folder_path === selectedFolder
        ? activeScan.files.length
        : selectedFolder
          ? 1
          : 0;
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
  const selectedDryRunWorker = workers.find((worker) => worker.id === dryRunWorkerId) ?? null;

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

  function openDryRunModal() {
    if (!activeSelection) {
      return;
    }
    setDryRunScheduleConflict(null);
    setDryRunModalOpen(true);
  }

  async function submitDryRun(ignoreWorkerSchedule = false) {
    if (!activeSelection) {
      return;
    }
    try {
      const result = await createDryRunJobsMutation.mutateAsync({
        ...activeSelection,
        pinned_worker_id: dryRunWorkerId || undefined,
        schedule_windows:
          !ignoreWorkerSchedule && selectedDryRunWorker?.schedule_windows?.length
            ? selectedDryRunWorker.schedule_windows
            : [],
        ignore_worker_schedule: ignoreWorkerSchedule,
      });
      setLatestDryRunJobIds(result.items.flatMap((item) => (item.job ? [item.job.id] : [])));
      setActiveTab("dry-run");
      setDryRunModalOpen(false);
      setDryRunScheduleConflict(null);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.details &&
        typeof error.details === "object" &&
        "detail" in error.details
      ) {
        const detail = (error.details as { detail: unknown }).detail;
        if (
          detail &&
          typeof detail === "object" &&
          "code" in detail &&
          (detail as { code: unknown }).code === "worker_schedule_conflict"
        ) {
          setDryRunScheduleConflict({
            worker_id: String((detail as { worker_id?: unknown }).worker_id ?? ""),
            worker_name: String((detail as { worker_name?: unknown }).worker_name ?? "Selected worker"),
            schedule_summary:
              detail && typeof detail === "object" && "schedule_summary" in detail
                ? String((detail as { schedule_summary?: unknown }).schedule_summary ?? "")
                : null,
          });
          return;
        }
      }
      return;
    }
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
      {createDryRunJobsMutation.error instanceof Error ? (
        <ErrorPanel title="Dry run failed" message={createDryRunJobsMutation.error.message} />
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
                  onClick={openDryRunModal}
                  disabled={!activeSelection || createDryRunJobsMutation.isPending}
                >
                  {createDryRunJobsMutation.isPending ? "Starting…" : "Dry Run"}
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
            dryRunJobs.length > 0 ? (
              <div className="card-stack">
                <div className="info-strip">
                  <strong>Worker-backed analysis</strong>
                  <span>Dry run jobs inspect and plan files on a worker without transcoding, deleting, or replacing media.</span>
                </div>
                <div className="metric-grid">
                  <div className="metric-panel">
                    <span className="metric-label">Files</span>
                    <strong>{dryRunJobs.length}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Completed</span>
                    <strong>{dryRunJobs.filter((item) => item.status === "completed").length}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Running</span>
                    <strong>{dryRunJobs.filter((item) => item.status === "running").length}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Would review</span>
                    <strong>{dryRunJobs.filter((item) => item.analysis_payload?.requires_review).length}</strong>
                  </div>
                </div>
                <div className="list-stack">
                  {dryRunJobs.map((item) => (
                    <div key={item.id} className="list-row">
                      <div>
                        <strong>{item.analysis_payload?.file_name ?? item.source_filename ?? item.source_path?.split("/").pop()}</strong>
                        <p>{item.analysis_payload?.source_path ?? item.source_path ?? "Path unavailable"}</p>
                        {item.analysis_payload ? (
                          <p>
                            {titleCase(item.analysis_payload.planned_action)} • {titleCase(item.analysis_payload.video_handling)} •
                            Estimated {formatBytes(item.analysis_payload.estimated_output_size_bytes)}
                          </p>
                        ) : (
                          <p>{titleCase(item.status)}{item.worker_name ? ` • ${item.worker_name}` : ""}</p>
                        )}
                        {item.analysis_payload?.summary ? <p>{item.analysis_payload.summary}</p> : null}
                      </div>
                      <div className="list-row-meta">
                        <StatusBadge value={item.status} />
                        <StatusBadge value="dry run" />
                        {item.analysis_payload ? <StatusBadge value={item.analysis_payload.planned_action} /> : null}
                        {item.analysis_payload?.requires_review ? <StatusBadge value="would review" /> : null}
                        <Link className="text-link" to={APP_ROUTES.jobDetail(item.id)}>Open job</Link>
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

      {dryRunModalOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Start dry run">
          <section className="modal-panel">
            <div className="card-stack">
              <div>
                <strong>Start dry run</strong>
                <p className="muted-copy">
                  Launch a safe analysis job on a worker. Dry run inspects and plans files without changing media.
                </p>
              </div>

              {dryRunSelectionCount > DRY_RUN_WARNING_THRESHOLD ? (
                <div className="info-strip info-strip-warning">
                  <strong>Large dry run</strong>
                  <span>
                    {dryRunSelectionCount} files are selected. Inspection can take some time once more than {DRY_RUN_WARNING_THRESHOLD} files are queued.
                  </span>
                </div>
              ) : null}

              <label className="field">
                <span>Worker</span>
                <select
                  aria-label="Dry run worker"
                  value={dryRunWorkerId}
                  onChange={(event) => {
                    setDryRunWorkerId(event.target.value);
                    setDryRunScheduleConflict(null);
                  }}
                >
                  <option value="">Automatic</option>
                  {workerOptions.map((worker) => (
                    <option key={worker.id} value={worker.id}>{worker.label}</option>
                  ))}
                </select>
              </label>

              {selectedDryRunWorker?.schedule_summary ? (
                <div className="info-strip">
                  <strong>Worker schedule</strong>
                  <span>{selectedDryRunWorker.schedule_summary}</span>
                </div>
              ) : null}

              {dryRunScheduleConflict ? (
                <div className="info-strip info-strip-warning">
                  <strong>Outside worker schedule</strong>
                  <span>
                    {dryRunScheduleConflict.worker_name} is currently outside its execution window.
                    {dryRunScheduleConflict.schedule_summary ? ` Allowed window: ${dryRunScheduleConflict.schedule_summary}.` : ""}
                  </span>
                </div>
              ) : null}

              <div className="section-card-actions">
                {dryRunScheduleConflict ? (
                  <>
                    <button
                      className="button button-primary"
                      type="button"
                      onClick={() => void submitDryRun(true)}
                      disabled={createDryRunJobsMutation.isPending}
                    >
                      {createDryRunJobsMutation.isPending ? "Starting…" : "Run now"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => void submitDryRun(false)}
                      disabled={createDryRunJobsMutation.isPending}
                    >
                      Queue for schedule
                    </button>
                  </>
                ) : (
                  <button
                    className="button button-primary"
                    type="button"
                    onClick={() => void submitDryRun(false)}
                    disabled={createDryRunJobsMutation.isPending}
                  >
                    {createDryRunJobsMutation.isPending ? "Starting…" : "Start dry run"}
                  </button>
                )}
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => {
                    setDryRunModalOpen(false);
                    setDryRunScheduleConflict(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </section>
        </div>
      ) : null}
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
