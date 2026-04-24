import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useRuntimeStatusQuery, useStorageStatusQuery, useWorkerStatusQuery } from "../../lib/api/hooks";
import { formatBytes, formatRelativeBoolean } from "../../lib/utils/format";

export function SystemPage() {
  const workerQuery = useWorkerStatusQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();

  const error = runtimeQuery.error ?? storageQuery.error;
  if (runtimeQuery.isLoading || storageQuery.isLoading) {
    return <LoadingBlock label="Loading system status" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load system status" message={error.message} />;
  }

  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;
  if (!runtime || !storage) {
    return <ErrorPanel title="System status is unavailable" message="The API did not return the expected system payload." />;
  }

  const combinedWarnings = dedupeWarnings([
    ...(runtime.warnings ?? []),
    ...(storage.warnings ?? []),
    ...([storage.scratch, storage.data_dir, ...storage.media_mounts]
      .filter((pathStatus) => pathStatus.status !== "healthy")
      .map((pathStatus) => `${pathStatus.display_name}: ${pathStatus.message}`)),
  ]);
  const runtimeTelemetry = readRuntimeTelemetry(runtime as unknown as Record<string, unknown>);

  async function refreshHealth() {
    await Promise.all([workerQuery.refetch(), runtimeQuery.refetch(), storageQuery.refetch()]);
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="System"
        title="System"
        description="Runtime and storage status."
        actions={
          <button
            className="button button-secondary"
            type="button"
            onClick={() => {
              void refreshHealth();
            }}
          >
            Refresh health
          </button>
        }
      />

      {combinedWarnings.length > 0 ? (
        <div className="system-alert-list">
          {combinedWarnings.map((warning) => (
            <div key={warning} className="system-alert-banner" role="alert">
              <span className="system-alert-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="M12 3 2.5 20.5h19L12 3Z" />
                  <path d="M12 9v5" />
                  <path d="M12 17.5h.01" />
                </svg>
              </span>
              <span>{warning}</span>
            </div>
          ))}
        </div>
      ) : null}

      <section className="system-status-grid">
        <HealthStatCard label="Runtime" status={runtime.status} value={runtime.summary} />
        <HealthStatCard label="Storage" status={storage.status} value={storage.summary} />
      </section>

      <SectionCard title="Runtime" subtitle="Live checks and active configuration sources.">
        <div className="card-stack">
          <div className="info-strip">
            <StatusBadge value={runtime.status} />
            <span>
              Version {runtime.version} • {runtime.environment} • auth {runtime.auth_enabled ? "on" : "off"}
            </span>
          </div>
          <div className="system-runtime-groups">
            <section className="system-metric-group" aria-label="Service health">
              <div>
                <h3>Service health</h3>
                <p>Database and account readiness.</p>
              </div>
              <div className="metric-grid metric-grid-compact">
                <HealthMetric label="DB reachable" value={formatRelativeBoolean(runtime.db_reachable)} />
                <HealthMetric label="Schema reachable" value={formatRelativeBoolean(runtime.schema_reachable)} />
                <HealthMetric label="User count" value={runtime.user_count == null ? "Not available" : String(runtime.user_count)} />
              </div>
            </section>
            <section className="system-metric-group" aria-label="Compute health">
              <div>
                <h3>Compute health</h3>
                <p>Host resource readings when reported by runtime.</p>
              </div>
              <RuntimeTelemetryGrid telemetry={runtimeTelemetry} />
            </section>
          </div>
          <div className="system-config-sources">
            <strong>Config sources</strong>
            <div className="system-config-source-list">
              {Object.entries(runtime.config_sources).map(([key, value]) => (
                <code key={key} className="system-config-source-chip">
                  {key}: {value}
                </code>
              ))}
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Storage" subtitle="Scratch, data, and media paths.">
        <div className="system-storage-grid">
          {[storage.scratch, storage.data_dir, ...storage.media_mounts].map((pathStatus) => (
            <article
              key={pathStatus.role + pathStatus.path}
              className={`system-storage-node ${
                pathStatus.status === "degraded" || pathStatus.status === "failed" ? "system-storage-node-alert" : ""
              }`}
            >
              <div className="badge-row">
                <StatusBadge value={pathStatus.status} />
                <strong>{pathStatus.display_name}</strong>
              </div>
              <p className="system-storage-path">{pathStatus.path}</p>
              <p className="muted-copy">{pathStatus.message}</p>
              {pathStatus.recommended_action ? (
                <div className="info-strip" role="note">
                  <strong>Recommended action</strong>
                  <span>{pathStatus.recommended_action}</span>
                </div>
              ) : null}
              <div className="system-storage-node-metrics">
                <HealthMetric label="Readable" value={formatRelativeBoolean(pathStatus.readable)} />
                <HealthMetric label="Writable" value={formatRelativeBoolean(pathStatus.writable)} />
                <HealthMetric label="Free space" value={formatBytes(pathStatus.free_space_bytes)} />
                <HealthMetric label="Total space" value={formatBytes(pathStatus.total_space_bytes)} />
              </div>
            </article>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

function dedupeWarnings(warnings: string[]): string[] {
  const seen = new Set<string>();
  return warnings.filter((warning) => {
    const key = warning
      .trim()
      .toLowerCase()
      .replace(/^[^:]+:\s*/, "");
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function readRuntimeTelemetry(runtime: Record<string, unknown>): Record<string, unknown> {
  const telemetry = runtime.telemetry;
  if (telemetry && typeof telemetry === "object" && !Array.isArray(telemetry)) {
    return telemetry as Record<string, unknown>;
  }
  return runtime;
}

function RuntimeTelemetryGrid({ telemetry }: { telemetry: Record<string, unknown> }) {
  const gpu = telemetry.gpu as Record<string, unknown> | null | undefined;
  return (
    <div className="metric-grid metric-grid-compact">
      <HealthMetric label="CPU" value={formatPercentMetric(telemetry.cpu_usage_percent)} />
      <HealthMetric label="Process CPU" value={formatPercentMetric(telemetry.process_cpu_usage_percent)} />
      <HealthMetric label="Memory" value={formatPercentMetric(telemetry.memory_usage_percent)} />
      <HealthMetric label="Process memory" value={formatBytes(readNumber(telemetry.process_memory_bytes))} />
      <HealthMetric label="CPU temp" value={formatTemperatureMetric(telemetry.cpu_temperature_c)} />
      <HealthMetric label="GPU" value={formatGpuMetric(gpu)} />
    </div>
  );
}

function formatPercentMetric(value: unknown): string {
  const number = readNumber(value);
  return number == null ? "Unavailable" : `${number.toFixed(1)}%`;
}

function formatTemperatureMetric(value: unknown): string {
  const number = readNumber(value);
  return number == null ? "Unavailable" : `${number.toFixed(1)}°C`;
}

function formatGpuMetric(gpu: Record<string, unknown> | null | undefined): string {
  if (!gpu) {
    return "Unavailable";
  }
  const vendor = typeof gpu.vendor === "string" ? gpu.vendor : "GPU";
  const usage = readNumber(gpu.usage_percent);
  if (usage != null) {
    return `${vendor} ${usage.toFixed(1)}%`;
  }
  const temperature = readNumber(gpu.temperature_c);
  if (temperature != null) {
    return `${vendor} ${temperature.toFixed(1)}°C`;
  }
  return typeof gpu.message === "string" ? gpu.message : vendor;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function HealthMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="metric-panel">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function HealthStatCard({
  label,
  status,
  value,
}: {
  label: string;
  status: string | undefined;
  value: string | number;
}) {
  return (
    <article className={`stat-card ${status === "degraded" || status === "failed" ? "stat-card-danger" : ""}`}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value health-stat-value">{value}</strong>
      <StatusBadge value={status} />
    </article>
  );
}
