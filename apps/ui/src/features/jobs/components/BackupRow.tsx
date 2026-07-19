import { JobBackup } from "../../../lib/types/api";
import { formatDateTime } from "../../../lib/utils/format";
import { formatBackupPolicy, shortId } from "../jobUtils";

export function BackupRow({
      item,
      selected,
      onSelectedChange,
      onDelete,
      onRestore,
      isBusy,
    }: {
          item: JobBackup;
          selected: boolean;
          onSelectedChange: (selected: boolean) => void;
          onDelete: () => void;
          onRestore: () => void;
          isBusy: boolean;
        }) {
    return (
    <article className="backup-list-row" role="listitem">
      <label className="backup-row-checkbox">
        <input
          type="checkbox"
          aria-label={`Select backup for ${item.source_filename ?? item.backup_path}`}
          checked={selected}
          onChange={(event) => onSelectedChange(event.target.checked)}
        />
      </label>
      <div>
        <strong>{item.source_filename ?? item.source_path?.split("/").pop() ?? `Job ${shortId(item.job_id)}`}</strong>
        <p className="muted-copy">{item.source_path ?? "Source path unavailable"}</p>
        <p className="muted-copy">
          Backup {item.backup_path} • {formatBackupPolicy(item.backup_policy)}
          {item.retention_until ? ` • retain until ${formatDateTime(item.retention_until)}` : ""}
        </p>
      </div>
      <div className="section-card-actions">
        <button className="button button-secondary button-small" type="button" onClick={onRestore} disabled={isBusy}>
          Restore
        </button>
        <button className="button button-secondary button-small" type="button" onClick={onDelete} disabled={isBusy}>
          Delete
        </button>
      </div>
    </article>
    );
}
