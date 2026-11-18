import { ResolveProblemAction } from "../jobUtils";

export function ResolveProblemJobsModal({
      count,
      isPending,
      onClose,
      onResolve,
    }: {
          count: number;
          isPending: boolean;
          onClose: () => void;
          onResolve: (action: ResolveProblemAction) => void;
        }) {
    return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Resolve selected failed jobs">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Resolve selected jobs?</strong>
            <p className="muted-copy">
              Retry moves {count} selected job{count === 1 ? "" : "s"} back to the queue. Mark skipped completes them as skipped so they will not be processed.
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onClose} disabled={isPending}>
              Cancel
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => onResolve("skip")}
              disabled={isPending}
            >
              Mark skipped
            </button>
            <button
              className="button button-primary"
              type="button"
              onClick={() => onResolve("retry")}
              disabled={isPending}
            >
              {isPending ? "Resolving…" : "Retry selected"}
            </button>
          </div>
        </div>
      </section>
    </div>
    );
}
