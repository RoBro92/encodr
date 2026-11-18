export function JobMetadataBadges({ items }: { items: string[] }) {
    const labels = items.length > 0 ? items : ["Media summary pending"];
    return (
    <div className="queue-job-card-metadata-badges" aria-label="Job media metadata">
      {labels.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
    );
}
