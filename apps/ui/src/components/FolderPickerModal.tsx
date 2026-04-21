import { useEffect, useState } from "react";

import { useBrowseFolderQuery } from "../lib/api/hooks";
import { ErrorPanel } from "./ErrorPanel";
import { LoadingBlock } from "./LoadingBlock";

export function FolderPickerModal({
  open,
  title,
  initialPath,
  onClose,
  onSelect,
}: {
  open: boolean;
  title: string;
  initialPath?: string | null;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const [currentPath, setCurrentPath] = useState<string | undefined>(initialPath ?? undefined);

  useEffect(() => {
    if (open) {
      setCurrentPath(initialPath ?? undefined);
    }
  }, [initialPath, open]);

  const browseQuery = useBrowseFolderQuery(open ? currentPath : undefined);

  if (!open) {
    return null;
  }

  const payload = browseQuery.data;
  const directories = payload?.entries.filter((entry) => entry.entry_type === "directory") ?? [];

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-panel">
        <div className="section-card-header">
          <div>
            <h2>{title}</h2>
            <p>{payload?.current_path ?? initialPath ?? "Loading folders…"}</p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary button-small" type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {browseQuery.isLoading ? <LoadingBlock label="Loading folders" /> : null}
        {browseQuery.error instanceof Error ? (
          <ErrorPanel title="Unable to browse folders" message={browseQuery.error.message} />
        ) : null}

        {payload ? (
          <div className="card-stack">
            <div className="section-card-actions">
              {payload.parent_path ? (
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => setCurrentPath(payload.parent_path ?? undefined)}
                >
                  Up one folder
                </button>
              ) : null}
              <button
                className="button button-primary button-small"
                type="button"
                onClick={() => onSelect(payload.current_path)}
              >
                Select this folder
              </button>
            </div>

            <div className="list-stack">
              {directories.map((entry) => (
                <div key={entry.path} className="list-row">
                  <div>
                    <strong>{entry.name}</strong>
                    <p>{entry.path}</p>
                  </div>
                  <div className="section-card-actions">
                    <button
                      className="button button-secondary button-small"
                      type="button"
                      onClick={() => setCurrentPath(entry.path)}
                    >
                      Open
                    </button>
                    <button
                      className="button button-primary button-small"
                      type="button"
                      onClick={() => onSelect(entry.path)}
                    >
                      Choose
                    </button>
                  </div>
                </div>
              ))}
              {directories.length === 0 ? (
                <div className="empty-inline">No folders are available here.</div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
