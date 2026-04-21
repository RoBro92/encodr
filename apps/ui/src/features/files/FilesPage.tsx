import { useState } from "react";
import { Link } from "react-router-dom";

import { FolderPickerModal } from "../../components/FolderPickerModal";
import { EmptyState } from "../../components/EmptyState";
import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useBatchPlanMutation,
  useCreateBatchJobsMutation,
  useDryRunMutation,
  useLibraryRootsQuery,
  useScanFolderMutation,
} from "../../lib/api/hooks";
import { titleCase } from "../../lib/utils/format";
import { APP_ROUTES } from "../../lib/utils/routes";

type LibraryTab = "browse" | "scan" | "dry-run" | "batch-plan";

export function FilesPage() {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<LibraryTab>("browse");

  const rootsQuery = useLibraryRootsQuery();
  const scanMutation = useScanFolderMutation();
  const dryRunMutation = useDryRunMutation();
  const batchPlanMutation = useBatchPlanMutation();
  const batchJobsMutation = useCreateBatchJobsMutation();

  if (rootsQuery.isLoading) {
    return <LoadingBlock label="Loading library" />;
  }

  if (rootsQuery.error instanceof Error) {
    return <ErrorPanel title="Unable to load the library" message={rootsQuery.error.message} />;
  }

  const roots = rootsQuery.data;
  if (!roots) {
    return <ErrorPanel title="Library is unavailable" message="The API did not return library roots." />;
  }

  const scanResult = scanMutation.data;
  const selectedSet = new Set(selectedPaths);
  const allSelected = Boolean(scanResult && scanResult.files.length > 0 && selectedPaths.length === scanResult.files.length);
  const hasSavedRoots = Boolean(roots.movies_root || roots.tv_root);
  const activeSelection =
    selectedPaths.length > 0
      ? { selected_paths: selectedPaths }
      : selectedFolder
        ? { folder_path: selectedFolder }
        : undefined;

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
  const selectedCount = selectedPaths.length;
  const showWorkspaceTabs = Boolean(selectedFolder);
  const currentTab = showWorkspaceTabs ? activeTab : "browse";

  function togglePath(path: string) {
    setSelectedPaths((current) =>
      current.includes(path) ? current.filter((item) => item !== path) : [...current, path],
    );
  }

  function selectAllVisible() {
    if (!scanResult) {
      return;
    }
    setSelectedPaths(scanResult.files.map((item) => item.path));
  }

  function clearSelection() {
    setSelectedPaths([]);
  }

  async function runScan(path: string) {
    setSelectedFolder(path);
    setSelectedPaths([]);
    setActiveTab("scan");
    await scanMutation.mutateAsync({ source_path: path });
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
              <button
                className="button button-primary"
                type="button"
                onClick={() => void runScan(selectedFolder)}
                disabled={scanMutation.isPending}
              >
                {scanMutation.isPending ? "Scanning…" : "Scan folder"}
              </button>
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
                {roots.movies_root ? (
                  <button className="button button-secondary button-small" type="button" onClick={() => void runScan(roots.movies_root!)}>
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
                {roots.tv_root ? (
                  <button className="button button-secondary button-small" type="button" onClick={() => void runScan(roots.tv_root!)}>
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
              </div>
              <strong className="library-path-copy">{selectedFolder ?? "No folder selected"}</strong>
              <p className="muted-copy">{selectionScopeCopy}</p>
            </div>

            <div className="library-header-metrics">
              <div className="metric-pill">
                <span className="metric-label">Selected</span>
                <strong>{selectedCount}</strong>
              </div>
              {scanResult?.folder_path === selectedFolder ? (
                <>
                  <div className="metric-pill">
                    <span className="metric-label">Video files</span>
                    <strong>{scanResult.video_file_count}</strong>
                  </div>
                  <div className="metric-pill">
                    <span className="metric-label">Likely films</span>
                    <strong>{scanResult.likely_film_count}</strong>
                  </div>
                  <div className="metric-pill">
                    <span className="metric-label">Likely episodes</span>
                    <strong>{scanResult.likely_episode_count}</strong>
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
                {scanMutation.isPending ? "Scanning…" : "Scan Folder"}
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
            scanMutation.isPending ? (
              <LoadingBlock label="Scanning folder" />
            ) : scanResult ? (
              <div className="card-stack">
                <div className="metric-grid">
                  <div className="metric-panel">
                    <span className="metric-label">Folders</span>
                    <strong>{scanResult.directory_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Video files</span>
                    <strong>{scanResult.video_file_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Likely films</span>
                    <strong>{scanResult.likely_film_count}</strong>
                  </div>
                  <div className="metric-panel">
                    <span className="metric-label">Likely episodes</span>
                    <strong>{scanResult.likely_episode_count}</strong>
                  </div>
                </div>

                <div className="library-selection-toolbar">
                  <div className="library-selection-copy">
                    <strong>{selectedPaths.length} selected</strong>
                    <span className="muted-copy">
                      {selectedPaths.length > 0 ? "Actions will use the selected files." : "No files selected. Actions will use the folder."}
                    </span>
                  </div>
                  <div className="section-card-actions">
                    <button className="button button-secondary button-small" type="button" onClick={allSelected ? clearSelection : selectAllVisible}>
                      {allSelected ? "Clear selection" : "Select all"}
                    </button>
                  </div>
                </div>

                <div className="selection-list">
                  {scanResult.files.map((file) => (
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
