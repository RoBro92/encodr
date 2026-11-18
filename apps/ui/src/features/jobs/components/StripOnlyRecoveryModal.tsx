export function StripOnlyRecoveryModal({
      isPending,
      onCancel,
      onConfirm,
    }: {
          isPending: boolean;
          onCancel: () => void;
          onConfirm: () => void;
        }) {
    return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Skip transcode / strip only">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Skip transcode / strip only</strong>
            <p className="muted-copy">
              This keeps the original video stream unchanged and only cleans audio and subtitle tracks using the current profile policy.
              The file is marked complete only after strip-only verification and replacement succeed.
            </p>
          </div>
          <div className="section-card-actions">
            <button className="button button-secondary" type="button" onClick={onCancel} disabled={isPending}>
              Cancel
            </button>
            <button className="button button-primary" type="button" onClick={onConfirm} disabled={isPending}>
              {isPending ? "Queueing…" : "Skip transcode / strip only"}
            </button>
          </div>
        </div>
      </section>
    </div>
    );
}
