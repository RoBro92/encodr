import { useState } from "react";

import { FolderPickerModal } from "../../components/FolderPickerModal";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useLibraryRootsQuery, useRuntimeStatusQuery, useStorageStatusQuery, useUpdateLibraryRootsMutation } from "../../lib/api/hooks";

type PickerTarget = "movies" | "tv" | null;

export function ConfigPage() {
  const [pickerTarget, setPickerTarget] = useState<PickerTarget>(null);
  const rootsQuery = useLibraryRootsQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const updateRootsMutation = useUpdateLibraryRootsMutation();

  const error = rootsQuery.error ?? runtimeQuery.error ?? storageQuery.error;
  const loading = rootsQuery.isLoading || runtimeQuery.isLoading || storageQuery.isLoading;

  if (loading) {
    return <LoadingBlock label="Loading setup" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load setup" message={error.message} />;
  }

  const roots = rootsQuery.data;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;
  if (!roots || !runtime || !storage) {
    return <ErrorPanel title="Setup is unavailable" message="The API did not return setup information." />;
  }

  const selectedRoot = pickerTarget === "movies" ? roots.movies_root : roots.tv_root;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Config"
        title="Setup"
        description="Choose your Movies and TV folders, then confirm storage is ready."
      />

      {updateRootsMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to save folders" message={updateRootsMutation.error.message} />
      ) : null}

      <section className="dashboard-grid">
        <SectionCard title="Library folders" subtitle="Choose the main folders you want to work from.">
          <div className="list-stack">
            <div className="list-row">
              <div>
                <strong>Movies root</strong>
                <p>{roots.movies_root ?? "Not selected yet"}</p>
              </div>
              <button className="button button-primary button-small" type="button" onClick={() => setPickerTarget("movies")}>
                Choose folder
              </button>
            </div>
            <div className="list-row">
              <div>
                <strong>TV root</strong>
                <p>{roots.tv_root ?? "Not selected yet"}</p>
              </div>
              <button className="button button-primary button-small" type="button" onClick={() => setPickerTarget("tv")}>
                Choose folder
              </button>
            </div>
            <div className="info-strip">
              <strong>Media root</strong>
              <span>{roots.media_root}</span>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Storage" subtitle="Check your library and scratch paths before running jobs.">
          <KeyValueList
            items={[
              { label: "Media root", value: storage.standard_media_root },
              { label: "Media status", value: <StatusBadge value={storage.media_mounts[0]?.status ?? "unknown"} /> },
              { label: "Scratch", value: <StatusBadge value={storage.scratch.status} /> },
              { label: "Runtime", value: <StatusBadge value={runtime.status} /> },
            ]}
          />
          {storage.warnings.length > 0 ? (
            <div className="card-stack">
              {storage.warnings.map((warning) => (
                <div key={warning} className="info-strip" role="note">
                  <span>{warning}</span>
                </div>
              ))}
            </div>
          ) : null}
        </SectionCard>
      </section>

      <SectionCard title="Current runtime" subtitle="A short view of the live setup.">
        <KeyValueList
          items={[
            { label: "Environment", value: runtime.environment },
            { label: "Version", value: runtime.version },
            { label: "Scratch path", value: runtime.scratch_dir },
            { label: "Data path", value: runtime.data_dir },
          ]}
        />
      </SectionCard>

      <FolderPickerModal
        open={pickerTarget !== null}
        title={pickerTarget === "movies" ? "Choose Movies folder" : "Choose TV folder"}
        initialPath={selectedRoot ?? roots.media_root}
        onClose={() => setPickerTarget(null)}
        onSelect={(path) => {
          const nextPayload =
            pickerTarget === "movies"
              ? { movies_root: path, tv_root: roots.tv_root }
              : { movies_root: roots.movies_root, tv_root: path };
          updateRootsMutation.mutate(nextPayload, {
            onSuccess: () => setPickerTarget(null),
          });
        }}
      />
    </div>
  );
}
