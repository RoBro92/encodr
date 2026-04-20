export function DashboardPage() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">encodr</p>
        <h1>Media ingestion preparation, kept narrow and reviewable.</h1>
        <p className="lede">
          This placeholder dashboard will become the operational view for queue
          state, worker health, storage posture, and recent file decisions.
        </p>
      </section>

      <section className="grid">
        <article className="panel">
          <h2>Queue</h2>
          <p>Local queue and job lifecycle views will land in Milestone 5.</p>
        </article>
        <article className="panel">
          <h2>Workers</h2>
          <p>Worker status, capabilities, and storage checks are planned later.</p>
        </article>
        <article className="panel">
          <h2>Policy</h2>
          <p>Policy summaries will expose YAML-backed rules without hiding detail.</p>
        </article>
        <article className="panel">
          <h2>Analytics</h2>
          <p>Processed counts, size saved, and preservation metrics will surface here.</p>
        </article>
      </section>
    </main>
  );
}

