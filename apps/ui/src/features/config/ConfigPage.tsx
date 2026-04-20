import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { useEffectiveConfigQuery } from "../../lib/api/hooks";

export function ConfigPage() {
  const configQuery = useEffectiveConfigQuery();

  if (configQuery.isLoading) {
    return <LoadingBlock label="Loading effective config" />;
  }

  if (configQuery.error instanceof Error) {
    return <ErrorPanel title="Unable to load effective config" message={configQuery.error.message} />;
  }

  const config = configQuery.data;
  if (!config) {
    return <ErrorPanel title="No config returned" message="The API did not return effective config data." />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Config"
        title="Effective configuration"
        description="Read-only visibility into the current sanitised app, policy, profile, and worker configuration."
      />

      <section className="dashboard-grid">
        <SectionCard title="App and auth" subtitle="Current high-level runtime settings.">
          <KeyValueList
            items={[
              { label: "App name", value: config.app_name },
              { label: "Environment", value: config.environment },
              { label: "Timezone", value: config.timezone },
              { label: "Scratch dir", value: config.scratch_dir },
              { label: "Data dir", value: config.data_dir },
              { label: "Session mode", value: config.auth.session_mode },
            ]}
          />
        </SectionCard>
        <SectionCard title="Policy" subtitle="Current sanitised policy summary.">
          <KeyValueList
            items={[
              { label: "Policy name", value: config.policy_name },
              { label: "Policy version", value: config.policy_version },
              { label: "Default container", value: config.output.default_container },
              { label: "Preferred audio languages", value: config.audio.keep_languages.join(", ") },
              { label: "Preferred subtitle languages", value: config.subtitles.keep_languages.join(", ") },
              { label: "Non-4K preferred codec", value: config.video.non_4k_preferred_codec },
              { label: "4K mode", value: config.video.four_k_mode },
            ]}
          />
        </SectionCard>
      </section>

      <section className="dashboard-grid">
        <SectionCard title="Profiles" subtitle="Available profile names and path override hints.">
          <div className="list-stack">
            {config.profiles.map((profile) => (
              <div key={profile.name} className="list-row">
                <div>
                  <strong>{profile.name}</strong>
                  <p>{profile.description ?? "No description provided."}</p>
                </div>
                <span>{profile.path_prefixes.length} path override(s)</span>
              </div>
            ))}
          </div>
        </SectionCard>
        <SectionCard title="Workers" subtitle="Configured worker definitions from the sanitised config view.">
          <div className="list-stack">
            {config.workers.map((worker) => (
              <div key={worker.id} className="list-row">
                <div>
                  <strong>{worker.id}</strong>
                  <p>{worker.host_or_endpoint}</p>
                </div>
                <span>{worker.queue}</span>
              </div>
            ))}
          </div>
        </SectionCard>
      </section>
    </div>
  );
}
