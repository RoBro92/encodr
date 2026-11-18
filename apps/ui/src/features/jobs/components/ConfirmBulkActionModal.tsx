export function ConfirmBulkActionModal({
      activeCount,
      isPending,
      onClose,
      onConfirm,
    }: {
          activeCount: number;
          isPending: boolean;
          onClose: () => void;
          onConfirm: () => void;
        }) {
    return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Clear queue"
    >
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Clear active queue?</strong>
              <p className="muted-copy">
                {`${activeCount} queued, scheduled, retryable interrupted, or waiting job${activeCount === 1 ? "" : "s"} will be cancelled. Running jobs are left alone.`}
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onClose} disabled={isPending}>
              Keep
            </button>
            <button className="button button-primary" type="button" onClick={onConfirm} disabled={isPending}>
              {isPending ? "Clearing…" : "Clear queue"}
            </button>
          </div>
        </div>
      </section>
    </div>
    );
}
