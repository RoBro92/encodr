import { BackupRetryStrategy } from "../jobUtils";

export function BackupRetryModal({
      count,
      isPending,
      onCancel,
      onRetry,
    }: {
          count: number;
          isPending: boolean;
          onCancel: () => void;
          onRetry: (strategy: BackupRetryStrategy) => void;
        }) {
    return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Backup already exists">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Backup already exists</strong>
            <p className="muted-copy">
              Choose how to handle the existing backup before retrying {count} selected job{count === 1 ? "" : "s"}.
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onCancel} disabled={isPending}>
              Cancel
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => onRetry("keep_existing_backup")}
              disabled={isPending}
            >
              Keep original
            </button>
            <button
              className="button button-primary"
              type="button"
              onClick={() => onRetry("replace_backup")}
              disabled={isPending}
            >
              Replace backup
            </button>
          </div>
        </div>
      </section>
    </div>
    );
}
