export function MixedProblemSelectionModal({ onClose }: { onClose: () => void }) {
    return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Mixed problem selection">
      <section className="modal-panel">
        <div className="card-stack">
          <div>
            <strong>Mixed problem selection</strong>
            <p className="muted-copy">Select jobs with the same error before using a bulk action.</p>
          </div>
          <div className="section-card-actions">
            <button className="button button-primary" type="button" onClick={onClose}>
              OK
            </button>
          </div>
        </div>
      </section>
    </div>
    );
}
