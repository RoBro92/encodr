import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { FolderPickerModal } from "../../components/FolderPickerModal";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { ScheduleWindowsEditor } from "../../components/ScheduleWindowsEditor";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useCreateBatchJobsMutation,
  useCreateDryRunJobsMutation,
  useCreateWatchedJobMutation,
  useFilesQuery,
  useJobsQuery,
  useLibraryRootsQuery,
  useScanFolderMutation,
  useScansQuery,
  useUpdateLibraryRootsMutation,
  useUpdateWatchedJobMutation,
  useWatchedJobsQuery,
  useWorkersQuery,
} from "../../lib/api/hooks";
import { ApiError } from "../../lib/api/client";
import type { FolderScanSummary, JobSummary, WatchedJob, WatchedJobPayload } from "../../lib/types/api";
import { formatBytes, formatDateTime, titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

type LibraryTab = "browse" | "scan" | "dry-run" | "jobs-created";
type RootKind = "movies" | "tv";
type PollingSchedule = "continuous" | "daily" | "overnight" | "weekend";

type WatcherDraft = WatchedJobPayload & {
  id?: string;
};

type DraftWatcherProfile = {
  profileId: string;
  draft: WatcherDraft;
};

type RootLibraryProfile = {
  id: `root:${RootKind}`;
  kind: "root";
  rootKind: RootKind;
  label: string;
  path: string;
  savedPath: string | null;
  watcher: WatchedJob | null;
};

type WatcherLibraryProfile = {
  id: `watcher:${string}`;
  kind: "watcher";
  watcher: WatchedJob;
  draft: WatcherDraft;
  label: string;
  path: string;
  savedPath: string;
};

type DraftLibraryProfile = {
  id: `draft:${string}`;
  kind: "draft";
  draft: WatcherDraft;
  label: string;
  path: string;
  savedPath: null;
};

type LibraryProfile = RootLibraryProfile | WatcherLibraryProfile | DraftLibraryProfile;

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
const LIBRARY_PAGE_SIZE = 25;

const ROOT_TABS: Array<{ key: RootKind; label: string }> = [
  { key: "movies", label: "Movies" },
  { key: "tv", label: "TV" },
];

const POLLING_SCHEDULE_OPTIONS: Array<{ value: PollingSchedule; label: string }> = [
  { value: "continuous", label: "Continuous" },
  { value: "daily", label: "Daily" },
  { value: "overnight", label: "Overnight" },
  { value: "weekend", label: "Weekends" },
];

type ScanKind = "movies" | "tv";
type ScanFileEntry = FolderScanSummary["files"][number] & {
  relative_path: string;
};
type TvSeasonGroup = {
  id: string;
  label: string;
  episodes: ScanFileEntry[];
  total_size_bytes: number;
};
type TvShowGroup = {
  id: string;
  label: string;
  seasons: TvSeasonGroup[];
  total_size_bytes: number;
  episode_count: number;
};

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
  const [activeLibraryKey, setActiveLibraryKey] = useState<LibraryProfile["id"]>("root:movies");
  const [rootDrafts, setRootDrafts] = useState<Record<RootKind, string>>({ movies: "", tv: "" });
  const [rootMonitoringEnabled, setRootMonitoringEnabled] = useState(true);
  const [rootPollingSchedule, setRootPollingSchedule] = useState<PollingSchedule>("daily");
  const [watcherConfigDrafts, setWatcherConfigDrafts] = useState<Record<string, WatcherDraft>>({});
  const [draftWatcherProfiles, setDraftWatcherProfiles] = useState<DraftWatcherProfile[]>([]);
  const [activeScanDraft, setActiveScanDraft] = useState<FolderScanSummary | null>(null);
  const [watcherDraft, setWatcherDraft] = useState<WatcherDraft | null>(null);
  const [dryRunModalOpen, setDryRunModalOpen] = useState(false);
  const [dryRunWorkerId, setDryRunWorkerId] = useState("");
  const [backupPolicy, setBackupPolicy] = useState("keep");
  const [dryRunScheduleConflict, setDryRunScheduleConflict] = useState<{
    worker_id: string;
    worker_name: string;
    schedule_summary: string | null;
  } | null>(null);
  const [latestDryRunJobIds, setLatestDryRunJobIds] = useState<string[]>([]);
  const [scanSearch, setScanSearch] = useState("");
  const [scanPage, setScanPage] = useState(1);
  const [expandedShows, setExpandedShows] = useState<Record<string, boolean>>({});
  const [expandedSeasons, setExpandedSeasons] = useState<Record<string, boolean>>({});

  const rootsQuery = useLibraryRootsQuery();
  const scansQuery = useScansQuery();
  const watchedJobsQuery = useWatchedJobsQuery();
  const workersQuery = useWorkersQuery();
  const allJobsQuery = useJobsQuery({ limit: 100 });
  const dryRunJobsQuery = useJobsQuery({ job_kind: "dry_run", limit: 100 });
  const scanMutation = useScanFolderMutation();
  const createDryRunJobsMutation = useCreateDryRunJobsMutation();
  const batchJobsMutation = useCreateBatchJobsMutation();
  const createWatchedJobMutation = useCreateWatchedJobMutation();
  const updateLibraryRootsMutation = useUpdateLibraryRootsMutation();
  const updateWatchedJobMutation = useUpdateWatchedJobMutation();

  const loading =
    rootsQuery.isLoading ||
    scansQuery.isLoading ||
    watchedJobsQuery.isLoading ||
    workersQuery.isLoading ||
    allJobsQuery.isLoading ||
    dryRunJobsQuery.isLoading;
  const error =
    rootsQuery.error ??
    scansQuery.error ??
    watchedJobsQuery.error ??
    workersQuery.error ??
    allJobsQuery.error ??
    dryRunJobsQuery.error;
  const roots = rootsQuery.data;
  const recentScans = scansQuery.data?.items ?? [];
  const watchedJobs = watchedJobsQuery.data?.items ?? [];
  const workers = workersQuery.data?.items ?? [];
  const allJobs = allJobsQuery.data?.items ?? [];
  const dryRunJobs = (dryRunJobsQuery.data?.items ?? []).filter((job) => latestDryRunJobIds.includes(job.id));
  const moviesRoot = roots?.movies_root ?? null;
  const tvRoot = roots?.tv_root ?? null;
  const rootWatcherByKind = useMemo(() => {
    const findRootWatcher = (kind: RootKind) => {
      const draftPath = rootDrafts[kind];
      const savedPath = kind === "movies" ? moviesRoot : tvRoot;
      return watchedJobs.find((item) => pathsMatch(item.source_path, draftPath) || pathsMatch(item.source_path, savedPath)) ?? null;
    };

    return {
      movies: findRootWatcher("movies"),
      tv: findRootWatcher("tv"),
    };
  }, [moviesRoot, rootDrafts, tvRoot, watchedJobs]);
  const nonRootWatchedJobs = useMemo(
    () =>
      watchedJobs.filter(
        (item) =>
          !pathsMatch(item.source_path, moviesRoot) &&
          !pathsMatch(item.source_path, tvRoot) &&
          !pathsMatch(item.source_path, rootDrafts.movies) &&
          !pathsMatch(item.source_path, rootDrafts.tv),
      ),
    [moviesRoot, rootDrafts.movies, rootDrafts.tv, tvRoot, watchedJobs],
  );
  const libraryProfiles = useMemo<LibraryProfile[]>(() => {
    const rootProfiles: RootLibraryProfile[] = ROOT_TABS.map((tab) => {
      const savedPath = tab.key === "movies" ? moviesRoot : tvRoot;
      return {
        id: `root:${tab.key}`,
        kind: "root",
        rootKind: tab.key,
        label: tab.label,
        path: rootDrafts[tab.key],
        savedPath,
        watcher: rootWatcherByKind[tab.key],
      };
    });

    const watcherProfiles: WatcherLibraryProfile[] = nonRootWatchedJobs.map((item) => {
      const draft = watcherConfigDrafts[item.id] ?? watcherDraftFromRecord(item);
      return {
        id: `watcher:${item.id}`,
        kind: "watcher",
        watcher: item,
        draft,
        label: draft.display_name || item.display_name || pathLabel(draft.source_path),
        path: draft.source_path,
        savedPath: item.source_path,
      };
    });

    const draftProfiles: DraftLibraryProfile[] = draftWatcherProfiles.map((item, index) => ({
      id: item.profileId as `draft:${string}`,
      kind: "draft",
      draft: item.draft,
      label: item.draft.display_name || pathLabel(item.draft.source_path) || `New Library ${index + 1}`,
      path: item.draft.source_path,
      savedPath: null,
    }));

    return [...rootProfiles, ...watcherProfiles, ...draftProfiles];
  }, [draftWatcherProfiles, moviesRoot, nonRootWatchedJobs, rootDrafts, rootWatcherByKind, tvRoot, watcherConfigDrafts]);
  const activeLibrary = libraryProfiles.find((profile) => profile.id === activeLibraryKey) ?? libraryProfiles[0];
  const activeRootKind = activeLibrary.kind === "root" ? activeLibrary.rootKind : null;
  const activeRootLabel = activeLibrary.label;
  const activeRootWatcher = activeLibrary.kind === "root" ? activeLibrary.watcher : null;
  const activeLibraryPath = activeLibrary.path;
  const activeLibrarySavedPath = activeLibrary.savedPath;
  const activeLibraryScopePath = activeLibraryPath.trim() || activeLibrarySavedPath || undefined;
  const activeLibraryWatcher = activeLibrary.kind === "watcher" ? activeLibrary.watcher : activeRootWatcher;
  const activeFileCountQuery = useFilesQuery({ path_prefix: activeLibraryScopePath, limit: 0 });
  const activeLibraryMonitoringEnabled = activeLibrary.kind === "root" ? rootMonitoringEnabled : activeLibrary.draft.enabled;
  const activeLibraryPollingSchedule =
    activeLibrary.kind === "root"
      ? rootPollingSchedule
      : pollingScheduleFromWindows(activeLibrary.draft.schedule_windows ?? []);
  const activeScan = activeScanDraft
    ? activeScanDraft.scan_id
      ? recentScans.find((item) => item.scan_id === activeScanDraft.scan_id) ?? activeScanDraft
      : activeScanDraft
    : null;

  const selectedSet = new Set(selectedPaths);
  const hasSavedRoots = Boolean(roots?.movies_root || roots?.tv_root);
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
  const scopedScans = useMemo(
    () =>
      recentScans.filter(
        (scan) =>
          pathsWithinScope(scan.folder_path, activeLibraryPath || activeLibrarySavedPath) ||
          Boolean(activeLibraryWatcher?.id && scan.watched_job_id === activeLibraryWatcher.id),
      ),
    [activeLibraryPath, activeLibrarySavedPath, activeLibraryWatcher?.id, recentScans],
  );
  const scopedJobs = useMemo(
    () =>
      allJobs.filter(
        (job) =>
          pathsWithinScope(job.source_path, activeLibraryPath || activeLibrarySavedPath) ||
          Boolean(activeLibraryWatcher?.id && job.watched_job_id === activeLibraryWatcher.id),
      ),
    [activeLibraryPath, activeLibrarySavedPath, activeLibraryWatcher?.id, allJobs],
  );
  const discoveredFileCount = useMemo(
    () => new Set(scopedScans.flatMap((scan) => scan.files.map((file) => file.path))).size,
    [scopedScans],
  );
  const persistedDiscoveredFileCount = Math.max(activeFileCountQuery.data?.total ?? 0, discoveredFileCount);
  const processedJobCount = scopedJobs.filter((job) => ["completed", "skipped"].includes(job.status)).length;
  const pendingProcessingCount = scopedJobs.filter((job) =>
    ["pending", "scheduled", "running"].includes(job.status),
  ).length;
  const selectionScopeLabel =
    selectedPaths.length > 0
      ? `${selectedPaths.length} file${selectedPaths.length === 1 ? "" : "s"} selected`
      : selectedFolder
        ? "Entire folder selected"
        : "No folder selected";
  const selectionScopeCopy =
    selectedPaths.length > 0
      ? "Dry run or create jobs for the selected files."
      : selectedFolder
        ? "Dry run or create jobs for the whole folder."
        : "Choose a folder to begin.";

  const workerOptions = workers.map((worker) => ({
    id: worker.id,
    label: `${worker.display_name} (${worker.worker_type === "local" ? "local" : "remote"})`,
  }));
  const selectedDryRunWorker = workers.find((worker) => worker.id === dryRunWorkerId) ?? null;
  const scanKind = useMemo(
    () => (activeScan ? inferScanKind(activeScan, moviesRoot, tvRoot) : "movies"),
    [activeScan, moviesRoot, tvRoot],
  );
  const scanFiles = useMemo(
    () => normaliseScanFiles(activeScan),
    [activeScan],
  );
  const tvGroups = useMemo(
    () => (scanKind === "tv" ? buildTvGroups(scanFiles, activeScan?.folder_path ?? "") : []),
    [scanFiles, scanKind, activeScan?.folder_path],
  );
  const filteredMovieFiles = useMemo(
    () => filterScanFiles(scanFiles, scanSearch),
    [scanFiles, scanSearch],
  );
  const filteredTvGroups = useMemo(
    () => filterTvGroups(tvGroups, scanSearch),
    [tvGroups, scanSearch],
  );
  const topLevelMovieFiles = useMemo(
    () => paginateItems(filteredMovieFiles, scanPage, LIBRARY_PAGE_SIZE),
    [filteredMovieFiles, scanPage],
  );
  const topLevelTvGroups = useMemo(
    () => paginateItems(filteredTvGroups, scanPage, LIBRARY_PAGE_SIZE),
    [filteredTvGroups, scanPage],
  );
  const visibleScanPaths = useMemo(
    () =>
      scanKind === "tv"
        ? topLevelTvGroups.flatMap((show) => show.seasons.flatMap((season) => season.episodes.map((episode) => episode.path)))
        : topLevelMovieFiles.map((file) => file.path),
    [scanKind, topLevelMovieFiles, topLevelTvGroups],
  );
  const totalTopLevelEntries = scanKind === "tv" ? filteredTvGroups.length : filteredMovieFiles.length;
  const totalPages = Math.max(1, Math.ceil(totalTopLevelEntries / LIBRARY_PAGE_SIZE));
  const allSelected = Boolean(
    activeScan &&
    visibleScanPaths.length > 0 &&
    visibleScanPaths.every((path) => selectedSet.has(path)),
  );

  useEffect(() => {
    setRootDrafts({
      movies: roots?.movies_root ?? "",
      tv: roots?.tv_root ?? "",
    });
  }, [roots?.movies_root, roots?.tv_root]);

  useEffect(() => {
    setWatcherConfigDrafts((current) => {
      let changed = false;
      const next = { ...current };
      const knownIds = new Set(watchedJobs.map((item) => item.id));

      for (const item of watchedJobs) {
        if (!next[item.id]) {
          next[item.id] = watcherDraftFromRecord(item);
          changed = true;
        }
      }

      for (const id of Object.keys(next)) {
        if (!knownIds.has(id)) {
          delete next[id];
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [watchedJobs]);

  useEffect(() => {
    if (!libraryProfiles.some((profile) => profile.id === activeLibraryKey)) {
      setActiveLibraryKey("root:movies");
    }
  }, [activeLibraryKey, libraryProfiles]);

  useEffect(() => {
    if (!activeRootKind) {
      return;
    }
    setRootMonitoringEnabled(activeRootWatcher?.enabled ?? true);
    setRootPollingSchedule(pollingScheduleFromWindows(activeRootWatcher?.schedule_windows ?? []));
  }, [activeRootKind, activeRootWatcher?.id, activeRootWatcher?.enabled, activeRootWatcher?.schedule_windows]);

  useEffect(() => {
    setScanSearch("");
    setScanPage(1);
    setExpandedShows({});
    setExpandedSeasons({});
  }, [activeScan?.scan_id, activeScan?.folder_path]);

  useEffect(() => {
    setScanPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  if (loading) {
    return <LoadingBlock label="Loading library" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load the library" message={error.message} />;
  }

  if (!roots) {
    return <ErrorPanel title="Library is unavailable" message="The API did not return library roots." />;
  }

  function togglePath(path: string) {
    setSelectedPaths((current) =>
      current.includes(path) ? current.filter((item) => item !== path) : [...current, path],
    );
  }

  function selectAllVisible() {
    if (!activeScan || visibleScanPaths.length === 0) {
      return;
    }
    setSelectedPaths((current) => {
      const next = new Set(current);
      for (const path of visibleScanPaths) {
        next.add(path);
      }
      return [...next];
    });
  }

  function clearSelection() {
    setSelectedPaths([]);
  }

  function togglePathGroup(paths: string[]) {
    if (paths.length === 0) {
      return;
    }
    const shouldSelect = paths.some((path) => !selectedSet.has(path));
    setSelectedPaths((current) => {
      const next = new Set(current);
      for (const path of paths) {
        if (shouldSelect) {
          next.add(path);
        } else {
          next.delete(path);
        }
      }
      return [...next];
    });
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

  function addWatcherProfile() {
    const profileId = `draft:${Date.now()}`;
    setDraftWatcherProfiles((current) => [
      ...current,
      {
        profileId,
        draft: {
          ...inferWatcherDefaults(null, moviesRoot, tvRoot),
          display_name: `New Library ${current.length + 1}`,
        },
      },
    ]);
    setActiveLibraryKey(profileId as LibraryProfile["id"]);
  }

  function updateActiveLibraryPath(path: string) {
    if (activeLibrary.kind === "root") {
      setRootDrafts((current) => ({
        ...current,
        [activeLibrary.rootKind]: path,
      }));
      return;
    }

    updateActiveWatcherProfileDraft((draft) => ({
      ...draft,
      source_path: path,
      display_name: draft.display_name?.startsWith("New Library") ? pathLabel(path) || draft.display_name : draft.display_name,
    }));
  }

  function updateActiveLibraryPollingSchedule(value: PollingSchedule) {
    if (activeLibrary.kind === "root") {
      setRootPollingSchedule(value);
      return;
    }

    updateActiveWatcherProfileDraft((draft) => ({
      ...draft,
      schedule_windows: scheduleWindowsForPolling(value),
    }));
  }

  function updateActiveLibraryMonitoringEnabled(enabled: boolean) {
    if (activeLibrary.kind === "root") {
      setRootMonitoringEnabled(enabled);
      return;
    }

    updateActiveWatcherProfileDraft((draft) => ({
      ...draft,
      enabled,
    }));
  }

  function updateActiveWatcherProfileDraft(updater: (draft: WatcherDraft) => WatcherDraft) {
    if (activeLibrary.kind === "watcher") {
      setWatcherConfigDrafts((current) => ({
        ...current,
        [activeLibrary.watcher.id]: updater(current[activeLibrary.watcher.id] ?? watcherDraftFromRecord(activeLibrary.watcher)),
      }));
      return;
    }

    if (activeLibrary.kind === "draft") {
      setDraftWatcherProfiles((current) =>
        current.map((item) =>
          item.profileId === activeLibrary.id
            ? { ...item, draft: updater(item.draft) }
            : item,
        ),
      );
    }
  }

  async function saveActiveLibrarySettings() {
    if (activeLibrary.kind === "root") {
      await saveRootWatchSettings(activeLibrary.rootKind);
      return;
    }

    const draft = activeLibrary.draft;
    const path = draft.source_path.trim();
    if (!path) {
      return;
    }

    const payload: WatchedJobPayload = {
      display_name: draft.display_name?.trim() || pathLabel(path) || "Watched folder",
      source_path: path,
      media_class: draft.media_class,
      ruleset_override: draft.ruleset_override,
      preferred_worker_id: draft.preferred_worker_id,
      pinned_worker_id: draft.pinned_worker_id,
      preferred_backend: draft.preferred_backend,
      schedule_windows: draft.schedule_windows,
      auto_queue: draft.auto_queue,
      stage_only: draft.stage_only,
      enabled: draft.enabled,
    };

    if (activeLibrary.kind === "watcher") {
      await updateWatchedJobMutation.mutateAsync({ watchedJobId: activeLibrary.watcher.id, payload });
      return;
    }

    const created = await createWatchedJobMutation.mutateAsync(payload);
    setDraftWatcherProfiles((current) => current.filter((item) => item.profileId !== activeLibrary.id));
    setActiveLibraryKey(`watcher:${created.id}`);
  }

  async function saveRootWatchSettings(kind: RootKind) {
    const path = rootDrafts[kind].trim();
    if (!path) {
      return;
    }
    const rootLabel = kind === "movies" ? "Movies" : "TV";
    const rootWatcher = rootWatcherByKind[kind];
    await updateLibraryRootsMutation.mutateAsync({
      movies_root: kind === "movies" ? path : moviesRoot,
      tv_root: kind === "tv" ? path : tvRoot,
    });

    const defaultDraft = inferWatcherDefaults(
      path,
      kind === "movies" ? path : moviesRoot,
      kind === "tv" ? path : tvRoot,
    );
    const payload: WatchedJobPayload = {
      display_name: rootWatcher?.display_name ?? `${rootLabel} watch`,
      source_path: path,
      media_class: rootWatcher?.media_class ?? defaultDraft.media_class,
      ruleset_override: rootWatcher?.ruleset_override ?? defaultDraft.ruleset_override,
      preferred_worker_id: rootWatcher?.preferred_worker_id ?? undefined,
      pinned_worker_id: rootWatcher?.pinned_worker_id ?? undefined,
      preferred_backend: rootWatcher?.preferred_backend ?? undefined,
      schedule_windows: scheduleWindowsForPolling(rootPollingSchedule),
      auto_queue: true,
      stage_only: false,
      enabled: rootMonitoringEnabled,
    };

    if (rootWatcher) {
      await updateWatchedJobMutation.mutateAsync({ watchedJobId: rootWatcher.id, payload });
    } else {
      await createWatchedJobMutation.mutateAsync(payload);
    }
  }

  async function scanLibrary() {
    const path = activeLibraryPath.trim() || activeLibrarySavedPath;
    if (!path) {
      return;
    }
    setSelectedFolder(path);
    setSelectedPaths([]);
    setActiveTab("scan");
    const scan = await scanMutation.mutateAsync({ source_path: path });
    setActiveScanDraft(scan);
  }

  async function processQueue() {
    const path = activeLibraryPath.trim() || activeLibrarySavedPath;
    if (!path) {
      return;
    }
    setSelectedFolder(path);
    setSelectedPaths([]);
    setActiveTab("jobs-created");
    await batchJobsMutation.mutateAsync({ folder_path: path, summary_only: true, backup_policy: backupPolicy });
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

  function runBatchJobs() {
    if (!activeSelection) {
      return;
    }
    setActiveTab("jobs-created");
    batchJobsMutation.mutate({ ...activeSelection, backup_policy: backupPolicy });
  }

  const tabs: Array<{ key: LibraryTab; label: string }> = [
    { key: "browse", label: "Browse" },
    { key: "scan", label: "Scan Results" },
    { key: "dry-run", label: "Dry Run" },
    { key: "jobs-created", label: "Jobs Created" },
  ];

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Library"
        title="Library"
        description="Configure automation, monitor processing, and manage your media libraries."
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
      {batchJobsMutation.error instanceof Error ? (
        <ErrorPanel title="Job creation failed" message={batchJobsMutation.error.message} />
      ) : null}
      {createWatchedJobMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to create watched job" message={createWatchedJobMutation.error.message} />
      ) : null}
      {updateLibraryRootsMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to update library roots" message={updateLibraryRootsMutation.error.message} />
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

      <section className="library-watch-section">
        <div className="library-root-tabs" role="tablist" aria-label="Library automation profiles">
          {libraryProfiles.map((profile) => (
            <button
              key={profile.id}
              className={`library-tab${activeLibrary.id === profile.id ? " library-tab-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={activeLibrary.id === profile.id}
              onClick={() => setActiveLibraryKey(profile.id)}
            >
              {profile.label}
            </button>
          ))}
          <button className="library-tab library-tab-add" type="button" onClick={addWatcherProfile}>
            + Add Watcher
          </button>
        </div>

        <div className="library-scoped-panel" role="tabpanel" aria-label={`${activeRootLabel} automation settings`}>
          <div className="library-watch-controls">
            <div className="library-watch-form">
              <label className="field">
                <span>Root directory</span>
                <input
                  aria-label={`${activeRootLabel} root directory`}
                  value={activeLibraryPath}
                  onChange={(event) => updateActiveLibraryPath(event.target.value)}
                  placeholder={activeRootKind === "movies" ? "/media/Movies" : activeRootKind === "tv" ? "/media/TV" : "/media/Library"}
                />
              </label>
              <label className="field">
                <span>Polling schedule</span>
                <select
                  aria-label={`${activeRootLabel} polling schedule`}
                  value={activeLibraryPollingSchedule}
                  onChange={(event) => updateActiveLibraryPollingSchedule(event.target.value as PollingSchedule)}
                >
                  {POLLING_SCHEDULE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <div className="field library-watch-toggle-field">
                <span>Enable monitoring</span>
                <button
                  className={`toggle-switch${activeLibraryMonitoringEnabled ? " toggle-switch-on" : ""}`}
                  type="button"
                  role="switch"
                  aria-label={`${activeRootLabel} enable monitoring`}
                  aria-checked={activeLibraryMonitoringEnabled}
                  onClick={() => updateActiveLibraryMonitoringEnabled(!activeLibraryMonitoringEnabled)}
                >
                  <span />
                </button>
              </div>
              <button
                className="button button-primary"
                type="button"
                onClick={() => void saveActiveLibrarySettings()}
                disabled={
                  !activeLibraryPath.trim() ||
                  updateLibraryRootsMutation.isPending ||
                  createWatchedJobMutation.isPending ||
                  updateWatchedJobMutation.isPending
                }
              >
                {updateLibraryRootsMutation.isPending || createWatchedJobMutation.isPending || updateWatchedJobMutation.isPending
                  ? "Saving…"
                  : "Save settings"}
              </button>
            </div>
          </div>

          <section className="library-processing-panel">
            <div className="section-card-header">
              <div>
                <h2>Processing dashboard</h2>
                <p>{activeRootLabel} stats are scoped to this library profile.</p>
              </div>
              <button
                className="button button-primary"
                type="button"
                onClick={() => void scanLibrary()}
                disabled={!activeLibraryPath.trim() || scanMutation.isPending}
              >
                {scanMutation.isPending ? "Scanning…" : "Scan Library"}
              </button>
              {persistedDiscoveredFileCount > 0 ? (
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => void processQueue()}
                  disabled={!activeLibraryPath.trim() || batchJobsMutation.isPending}
                >
                  {batchJobsMutation.isPending ? "Queueing…" : "Process Queue"}
                </button>
              ) : null}
            </div>

            <div className="library-processing-stats">
              <div className="library-processing-stat">
                <span className="metric-label">Total Files Discovered</span>
                <strong>{persistedDiscoveredFileCount}</strong>
              </div>
              <div className="library-processing-stat">
                <span className="metric-label">Successfully Processed</span>
                <strong>{processedJobCount}</strong>
              </div>
              <div className="library-processing-stat">
                <span className="metric-label">Pending Processing</span>
                <strong>{pendingProcessingCount}</strong>
              </div>
            </div>
          </section>
        </div>
      </section>

      <div className="dashboard-grid library-activity-grid">
        <SectionCard
          title="Recent scans"
          subtitle="Reopen saved scan results or rescan a folder when it changes."
        >
          {recentScans.length === 0 ? (
            <EmptyState title="No saved scans yet" message="Run a folder scan to keep the result available for later job creation." />
          ) : (
            <div className="list-stack library-recent-scans-list">
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
          title="Active Watchers"
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
              <div className="library-watchers-empty">
                <EmptyState title="No watched folders yet" message="Create a watched job to queue or stage new files automatically from an SSD or library path." />
              </div>
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

      <CollapsibleSection
        title="Advanced Options"
        subtitle="Manual browsing, selection, dry-run analysis, and job creation"
      >
        <div className="library-advanced-toolbar">
          <div className="library-advanced-toolbar-left">
            <strong>{selectedCountLabel}</strong>
            <StatusBadge value={selectedFolder ? "pending" : "idle"} />
            <span className="muted-copy">{selectionScopeLabel}</span>
          </div>
          <div className="library-advanced-toolbar-actions">
            <label className="field field-inline">
              <span>Backup policy</span>
              <select value={backupPolicy} onChange={(event) => setBackupPolicy(event.target.value)}>
                <option value="keep">Keep backup</option>
                <option value="keep_for_1_day">Keep for 1 day</option>
                <option value="delete_after_success">Delete after success</option>
              </select>
            </label>
            <button
              className="button button-secondary button-small"
              type="button"
              onClick={() => selectedFolder && void runScan(selectedFolder)}
              disabled={!selectedFolder || scanMutation.isPending}
            >
              {scanMutation.isPending ? "Scanning…" : "Scan folder"}
            </button>
            <button
              className="button button-primary button-small"
              type="button"
              onClick={openDryRunModal}
              disabled={!activeSelection || createDryRunJobsMutation.isPending}
            >
              {createDryRunJobsMutation.isPending ? "Starting…" : "Dry Run"}
            </button>
            <button
              className="button button-primary button-small"
              type="button"
              onClick={runBatchJobs}
              disabled={!activeSelection || batchJobsMutation.isPending}
            >
              {batchJobsMutation.isPending ? "Creating…" : "Create Jobs"}
            </button>
          </div>
        </div>

        <div className="library-advanced-context">
          <strong className="library-path-copy">{selectedFolder ?? "No folder selected"}</strong>
          <p className="muted-copy">{selectionScopeCopy}</p>
          {activeScan?.scanned_at ? <p className="muted-copy">Last scan {formatDateTime(activeScan.scanned_at)}</p> : null}
        </div>

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

                <div className="jobs-toolbar">
                  <label className="field">
                    <span>Search this scan</span>
                    <input
                      aria-label="Search scan results"
                      value={scanSearch}
                      placeholder={scanKind === "tv" ? "Search shows, seasons, or episodes" : "Search films"}
                      onChange={(event) => {
                        setScanSearch(event.target.value);
                        setScanPage(1);
                      }}
                    />
                  </label>
                  <div className="metric-pill">
                    <span className="metric-label">Top-level entries</span>
                    <strong>{totalTopLevelEntries}</strong>
                  </div>
                  <div className="metric-pill">
                    <span className="metric-label">Page</span>
                    <strong>{scanPage} / {totalPages}</strong>
                  </div>
                </div>

                {totalTopLevelEntries === 0 ? (
                  <EmptyState
                    title="No matching items"
                    message={scanSearch ? "Try a different search term or clear the filter." : "This scan did not return any video items."}
                  />
                ) : scanKind === "tv" ? (
                  <div className="card-stack">
                    {topLevelTvGroups.map((show) => {
                      const showPaths = show.seasons.flatMap((season) => season.episodes.map((episode) => episode.path));
                      const showSelected = showPaths.length > 0 && showPaths.every((path) => selectedSet.has(path));
                      const showExpanded = expandedShows[show.id] ?? true;
                      return (
                        <section key={show.id} className="job-worker-group">
                          <button
                            className="job-worker-group-summary job-worker-group-trigger"
                            type="button"
                            aria-expanded={showExpanded}
                            onClick={() =>
                              setExpandedShows((current) => ({
                                ...current,
                                [show.id]: !(current[show.id] ?? true),
                              }))
                            }
                          >
                            <div className="job-worker-group-heading">
                              <strong>{show.label}</strong>
                              <span>{show.episode_count} episodes • {formatBytes(show.total_size_bytes)}</span>
                            </div>
                            <div className="job-worker-group-metrics">
                              <span>{show.seasons.length} seasons</span>
                              <span>{showSelected ? "Selected" : "Not fully selected"}</span>
                              <span>{showPaths.filter((path) => selectedSet.has(path)).length} selected</span>
                            </div>
                          </button>
                          {showExpanded ? (
                            <div className="record-list">
                              <div className="section-card-actions">
                                <button className="button button-secondary button-small" type="button" onClick={() => togglePathGroup(showPaths)}>
                                  {showSelected ? "Clear show" : "Select show"}
                                </button>
                              </div>
                              {show.seasons.map((season) => {
                                const seasonPaths = season.episodes.map((episode) => episode.path);
                                const seasonSelected = seasonPaths.length > 0 && seasonPaths.every((path) => selectedSet.has(path));
                                const seasonExpanded = expandedSeasons[season.id] ?? false;
                                return (
                                  <section key={season.id} className="job-worker-group">
                                    <button
                                      className="job-worker-group-summary job-worker-group-trigger"
                                      type="button"
                                      aria-expanded={seasonExpanded}
                                      onClick={() =>
                                        setExpandedSeasons((current) => ({
                                          ...current,
                                          [season.id]: !(current[season.id] ?? false),
                                        }))
                                      }
                                    >
                                      <div className="job-worker-group-heading">
                                        <strong>{season.label}</strong>
                                        <span>{season.episodes.length} episodes • {formatBytes(season.total_size_bytes)}</span>
                                      </div>
                                      <div className="job-worker-group-metrics">
                                        <span>{seasonSelected ? "Selected" : "Not fully selected"}</span>
                                      </div>
                                    </button>
                                    {seasonExpanded ? (
                                      <div className="record-list">
                                        <div className="section-card-actions">
                                          <button className="button button-secondary button-small" type="button" onClick={() => togglePathGroup(seasonPaths)}>
                                            {seasonSelected ? "Clear season" : "Select season"}
                                          </button>
                                        </div>
                                        {season.episodes.map((file) => (
                                          <label key={file.path} className={`selection-row${selectedSet.has(file.path) ? " selection-row-active" : ""}`}>
                                            <input
                                              type="checkbox"
                                              aria-label={`Select ${file.name}`}
                                              checked={selectedSet.has(file.path)}
                                              onChange={() => togglePath(file.path)}
                                            />
                                            <div>
                                              <strong>{file.name}</strong>
                                              <p>{file.relative_path}</p>
                                            </div>
                                            <span className="selection-row-meta">{formatBytes(file.size_bytes)}</span>
                                          </label>
                                        ))}
                                      </div>
                                    ) : null}
                                  </section>
                                );
                              })}
                            </div>
                          ) : null}
                        </section>
                      );
                    })}
                  </div>
                ) : (
                  <div className="selection-list">
                    {topLevelMovieFiles.map((file) => (
                      <label key={file.path} className={`selection-row${selectedSet.has(file.path) ? " selection-row-active" : ""}`}>
                        <input
                          type="checkbox"
                          aria-label={`Select ${file.name}`}
                          checked={selectedSet.has(file.path)}
                          onChange={() => togglePath(file.path)}
                        />
                        <div>
                          <strong>{file.name}</strong>
                          <p>{file.relative_path}</p>
                        </div>
                        <span className="selection-row-meta">{formatBytes(file.size_bytes)}</span>
                      </label>
                    ))}
                  </div>
                )}

                {totalPages > 1 ? (
                  <div className="section-card-actions">
                    <button
                      className="button button-secondary button-small"
                      type="button"
                      onClick={() => setScanPage((current) => Math.max(1, current - 1))}
                      disabled={scanPage <= 1}
                    >
                      Previous
                    </button>
                    <span className="muted-copy">Page {scanPage} of {totalPages}</span>
                    <button
                      className="button button-secondary button-small"
                      type="button"
                      onClick={() => setScanPage((current) => Math.min(totalPages, current + 1))}
                      disabled={scanPage >= totalPages}
                    >
                      Next
                    </button>
                  </div>
                ) : null}
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

          {currentTab === "jobs-created" ? (
            batchJobsMutation.data ? (
              <div className="card-stack">
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
              </div>
            ) : (
              <EmptyState title="No jobs created yet" message="Run Create Jobs when you are ready to save work." />
            )
          ) : null}
        </div>
      </CollapsibleSection>

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

function pathLabel(path: string | null | undefined) {
  return path?.split("/").filter(Boolean).at(-1) ?? "";
}

function normalisePath(path: string | null | undefined) {
  const trimmed = path?.trim().replace(/\/+$/, "") ?? "";
  return trimmed || null;
}

function pathsMatch(left: string | null | undefined, right: string | null | undefined) {
  const normalisedLeft = normalisePath(left);
  const normalisedRight = normalisePath(right);
  return Boolean(normalisedLeft && normalisedRight && normalisedLeft === normalisedRight);
}

function pathsWithinScope(path: string | null | undefined, scope: string | null | undefined) {
  const normalisedPath = normalisePath(path);
  const normalisedScope = normalisePath(scope);
  if (!normalisedPath || !normalisedScope) {
    return false;
  }
  return normalisedPath === normalisedScope || normalisedPath.startsWith(`${normalisedScope}/`);
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

function scheduleWindowsForPolling(value: PollingSchedule) {
  if (value === "continuous") {
    return [];
  }
  if (value === "weekend") {
    return [
      { days: ["sat", "sun"], start_time: "00:00", end_time: "23:59" },
    ];
  }
  if (value === "overnight") {
    return [
      { days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start_time: "00:00", end_time: "06:00" },
    ];
  }
  return [
    { days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start_time: "02:00", end_time: "04:00" },
  ];
}

function pollingScheduleFromWindows(windows: WatchedJob["schedule_windows"]): PollingSchedule {
  if (windows.length === 0) {
    return "continuous";
  }
  if (windows.length === 1) {
    const [window] = windows;
    const days = [...window.days].sort().join(",");
    if (days === "sat,sun" && window.start_time === "00:00" && window.end_time === "23:59") {
      return "weekend";
    }
    if (window.start_time === "00:00" && window.end_time === "06:00") {
      return "overnight";
    }
  }
  return "daily";
}

function inferScanKind(scan: FolderScanSummary, moviesRoot: string | null, tvRoot: string | null): ScanKind {
  if (tvRoot && scan.folder_path.startsWith(tvRoot)) {
    return "tv";
  }
  if (moviesRoot && scan.folder_path.startsWith(moviesRoot)) {
    return "movies";
  }
  return scan.likely_episode_count > scan.likely_film_count ? "tv" : "movies";
}

function normaliseScanFiles(scan: FolderScanSummary | null): ScanFileEntry[] {
  if (!scan) {
    return [];
  }
  return scan.files.map((file) => ({
    ...file,
    relative_path: file.path.startsWith(scan.folder_path)
      ? file.path.slice(scan.folder_path.length).replace(/^\/+/, "") || file.name
      : file.name,
  }));
}

function filterScanFiles(files: ScanFileEntry[], search: string) {
  if (!search.trim()) {
    return files;
  }
  const needle = search.trim().toLowerCase();
  return files.filter((file) =>
    file.name.toLowerCase().includes(needle) ||
    file.relative_path.toLowerCase().includes(needle) ||
    file.path.toLowerCase().includes(needle),
  );
}

function buildTvGroups(files: ScanFileEntry[], folderPath: string): TvShowGroup[] {
  const groups = new Map<string, TvShowGroup>();
  const folderName = folderPath.split("/").filter(Boolean).at(-1) ?? "Show";
  for (const file of files) {
    const segments = file.relative_path.split("/").filter(Boolean);
    const showLabel =
      segments.length >= 3
        ? segments[0]
        : segments.length >= 2 && isSeasonLabel(segments[0])
          ? folderName
          : segments[0] ?? folderName;
    const seasonLabel =
      segments.length >= 3
        ? segments[1]
        : segments.length >= 2
          ? segments[0]
          : "Episodes";
    const showKey = showLabel.toLowerCase();
    const seasonKey = `${showKey}:${seasonLabel.toLowerCase()}`;
    const show = groups.get(showKey) ?? {
      id: showKey,
      label: showLabel,
      seasons: [],
      total_size_bytes: 0,
      episode_count: 0,
    };
    let season = show.seasons.find((item) => item.id === seasonKey);
    if (!season) {
      season = {
        id: seasonKey,
        label: seasonLabel,
        episodes: [],
        total_size_bytes: 0,
      };
      show.seasons.push(season);
    }
    season.episodes.push(file);
    season.total_size_bytes += file.size_bytes ?? 0;
    show.total_size_bytes += file.size_bytes ?? 0;
    show.episode_count += 1;
    groups.set(showKey, show);
  }
  return [...groups.values()].sort((left, right) => left.label.localeCompare(right.label));
}

function filterTvGroups(groups: TvShowGroup[], search: string) {
  if (!search.trim()) {
    return groups;
  }
  const needle = search.trim().toLowerCase();
  return groups
    .map((show) => {
      if (show.label.toLowerCase().includes(needle)) {
        return show;
      }
      const seasons = show.seasons
        .map((season) => {
          if (season.label.toLowerCase().includes(needle)) {
            return season;
          }
          const episodes = season.episodes.filter((episode) =>
            episode.name.toLowerCase().includes(needle) ||
            episode.relative_path.toLowerCase().includes(needle),
          );
          if (episodes.length === 0) {
            return null;
          }
          return {
            ...season,
            episodes,
            total_size_bytes: episodes.reduce((sum, item) => sum + (item.size_bytes ?? 0), 0),
          };
        })
        .filter((season): season is TvSeasonGroup => season !== null);
      if (seasons.length === 0) {
        return null;
      }
      return {
        ...show,
        seasons,
        total_size_bytes: seasons.reduce((sum, item) => sum + item.total_size_bytes, 0),
        episode_count: seasons.reduce((sum, item) => sum + item.episodes.length, 0),
      };
    })
    .filter((show): show is TvShowGroup => show !== null);
}

function paginateItems<T>(items: T[], page: number, pageSize: number) {
  const start = (page - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

function isSeasonLabel(value: string) {
  return /^season\s*\d+$/i.test(value) || /^s\d{1,2}$/i.test(value);
}
