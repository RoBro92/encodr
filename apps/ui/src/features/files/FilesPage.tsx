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
import { APP_ROUTES } from "../../lib/utils/routes";
import { titleCase } from "../../lib/utils/format";

export function FilesPage() {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);

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

  const activeSelection =
    selectedPaths.length > 0
      ? { selected_paths: selectedPaths }
      : selectedFolder
        ? { folder_path: selectedFolder }
        : undefined;

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
    await scanMutation.mutateAsync({ source_path: path });
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Library"
        title="Library"
        description="Browse your mounted folders, scan a location, run a dry run, or create jobs in batches."
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

      <section className="dashboard-grid">
        <SectionCard title="Library roots" subtitle="Use your saved roots or choose another folder under /media.">
          <div className="list-stack">
            <div className="list-row">
              <div>
                <strong>Movies</strong>
                <p>{roots.movies_root ?? "Choose this on the Config page."}</p>
              </div>
              <div className="section-card-actions">
                {roots.movies_root ? (
                  <button className="button button-primary button-small" type="button" onClick={() => void runScan(roots.movies_root!)}>
                    Scan
                  </button>
                ) : (
                  <Link className="button button-secondary button-small" to={APP_ROUTES.config}>
                    Set folder
                  </Link>
                )}
              </div>
            </div>
            <div className="list-row">
              <div>
                <strong>TV</strong>
                <p>{roots.tv_root ?? "Choose this on the Config page."}</p>
              </div>
              <div className="section-card-actions">
                {roots.tv_root ? (
                  <button className="button button-primary button-small" type="button" onClick={() => void runScan(roots.tv_root!)}>
                    Scan
                  </button>
                ) : (
                  <Link className="button button-secondary button-small" to={APP_ROUTES.config}>
                    Set folder
                  </Link>
                )}
              </div>
            </div>
            <div className="section-card-actions">
              <button className="button button-secondary button-small" type="button" onClick={() => setPickerOpen(true)}>
                Browse folders
              </button>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Workflow" subtitle="Dry run stays read-only. Batch planning and jobs persist real state.">
          <div className="card-stack">
            <div className="metric-grid">
              <div className="metric-panel">
                <span className="metric-label">Dry run</span>
                <strong>Plan only</strong>
                <span className="metric-subtle">No output files or replacements.</span>
              </div>
              <div className="metric-panel">
                <span className="metric-label">Batch plan</span>
                <strong>Persist plans</strong>
                <span className="metric-subtle">Creates tracked file and plan history.</span>
              </div>
              <div className="metric-panel">
                <span className="metric-label">Create jobs</span>
                <strong>Queue work</strong>
                <span className="metric-subtle">Manual review still blocks protected items.</span>
              </div>
            </div>
          </div>
        </SectionCard>
      </section>

      <SectionCard
        title="Scan results"
        subtitle={scanResult ? scanResult.folder_path : "Choose a folder to scan."}
        actions={
          <div className="section-card-actions">
            <button className="button button-secondary button-small" type="button" onClick={() => setPickerOpen(true)}>
              Choose folder
            </button>
            <Link className="button button-secondary button-small" to={APP_ROUTES.config}>
              Set roots
            </Link>
          </div>
        }
      >
        {scanMutation.isPending ? (
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

            <div className="section-card-actions">
              <button className="button button-secondary button-small" type="button" onClick={allSelected ? clearSelection : selectAllVisible}>
                {allSelected ? "Clear selection" : "Select all files"}
              </button>
              <button
                className="button button-secondary button-small"
                type="button"
                onClick={() => activeSelection && dryRunMutation.mutate(activeSelection)}
                disabled={!activeSelection || dryRunMutation.isPending}
              >
                {dryRunMutation.isPending ? "Running dry run…" : selectedPaths.length > 0 ? "Dry run selected" : "Dry run folder"}
              </button>
              <button
                className="button button-secondary button-small"
                type="button"
                onClick={() => activeSelection && batchPlanMutation.mutate(activeSelection)}
                disabled={!activeSelection || batchPlanMutation.isPending}
              >
                {batchPlanMutation.isPending ? "Planning…" : selectedPaths.length > 0 ? "Plan selected" : "Plan folder"}
              </button>
              <button
                className="button button-primary button-small"
                type="button"
                onClick={() => activeSelection && batchJobsMutation.mutate(activeSelection)}
                disabled={!activeSelection || batchJobsMutation.isPending}
              >
                {batchJobsMutation.isPending ? "Creating jobs…" : selectedPaths.length > 0 ? "Create jobs for selected" : "Create jobs for folder"}
              </button>
            </div>

            <div className="selection-list">
              {scanResult.files.map((file) => (
                <label key={file.path} className="selection-row">
                  <input type="checkbox" checked={selectedSet.has(file.path)} onChange={() => togglePath(file.path)} />
                  <div>
                    <strong>{file.name}</strong>
                    <p>{file.path}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState title="No folder scanned yet" message="Pick a folder from your library roots or browse under /media." />
        )}
      </SectionCard>

      {dryRunMutation.data ? (
        <SectionCard title="Dry run" subtitle="Read-only preview of what Encodr would do.">
          <div className="card-stack">
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
        </SectionCard>
      ) : null}

      {batchPlanMutation.data ? (
        <SectionCard title="Saved plans" subtitle="These plans were written to Encodr’s history.">
          <div className="card-stack">
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
        </SectionCard>
      ) : null}

      {batchJobsMutation.data ? (
        <SectionCard title="Batch jobs" subtitle="Created jobs are queued. Blocked items still need review or protection approval.">
          <div className="card-stack">
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
        </SectionCard>
      ) : null}

      <FolderPickerModal
        open={pickerOpen}
        title="Browse library folders"
        initialPath={roots.movies_root ?? roots.tv_root ?? roots.media_root}
        onClose={() => setPickerOpen(false)}
        onSelect={(path) => {
          setPickerOpen(false);
          void runScan(path);
        }}
      />
    </div>
  );
}
