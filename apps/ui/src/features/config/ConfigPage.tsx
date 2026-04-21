import { useEffect, useMemo, useState } from "react";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { FolderPickerModal } from "../../components/FolderPickerModal";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useEffectiveConfigQuery,
  useLibraryRootsQuery,
  useProcessingRulesQuery,
  useRuntimeStatusQuery,
  useStorageStatusQuery,
  useUpdateLibraryRootsMutation,
  useUpdateProcessingRulesMutation,
} from "../../lib/api/hooks";
import type { ProcessingRules, ProcessingRuleset, ProcessingRuleValues } from "../../lib/types/api";

type PickerTarget = "movies" | "tv" | null;
type RulesetKey = "movies" | "tv";

const VIDEO_CODEC_OPTIONS = [
  { label: "H.265 / HEVC", value: "hevc" },
  { label: "H.264 / AVC", value: "h264" },
  { label: "AV1", value: "av1" },
  { label: "MPEG-2", value: "mpeg2" },
  { label: "VP9", value: "vp9" },
];

const CONTAINER_OPTIONS = [
  { label: "MKV", value: "mkv" },
  { label: "MP4", value: "mp4" },
];

const FOUR_K_MODE_OPTIONS = [
  { label: "Strip only", value: "strip_only" },
  { label: "Policy controlled", value: "policy_controlled" },
];

export function ConfigPage() {
  const [pickerTarget, setPickerTarget] = useState<PickerTarget>(null);
  const [rulesDraft, setRulesDraft] = useState<ProcessingRules | null>(null);
  const [persistedRules, setPersistedRules] = useState<ProcessingRules | null>(null);
  const rootsQuery = useLibraryRootsQuery();
  const rulesQuery = useProcessingRulesQuery();
  const effectiveConfigQuery = useEffectiveConfigQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const updateRootsMutation = useUpdateLibraryRootsMutation();
  const updateRulesMutation = useUpdateProcessingRulesMutation();

  useEffect(() => {
    if (rulesQuery.data) {
      setRulesDraft(rulesQuery.data);
      setPersistedRules(rulesQuery.data);
    }
  }, [rulesQuery.data]);

  const error =
    rootsQuery.error ??
    rulesQuery.error ??
    effectiveConfigQuery.error ??
    runtimeQuery.error ??
    storageQuery.error;
  const loading =
    rootsQuery.isLoading ||
    rulesQuery.isLoading ||
    effectiveConfigQuery.isLoading ||
    runtimeQuery.isLoading ||
    storageQuery.isLoading;

  if (loading) {
    return <LoadingBlock label="Loading settings" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load settings" message={error.message} />;
  }

  const roots = rootsQuery.data;
  const rules = rulesDraft;
  const effectiveConfig = effectiveConfigQuery.data;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;
  if (!roots || !runtime || !storage || !effectiveConfig || !rules) {
    return <ErrorPanel title="Settings are unavailable" message="The API did not return settings information." />;
  }

  const selectedRoot = pickerTarget === "movies" ? roots.movies_root : roots.tv_root;
  const buildRulesPayload = (target: RulesetKey, nextValues: ProcessingRuleValues | null) => {
    const baseline = persistedRules ?? rulesQuery.data;
    if (!baseline) {
      throw new Error("Processing rules are unavailable.");
    }
    return {
      movies: target === "movies" ? nextValues : baseline.movies.uses_defaults ? null : baseline.movies.current,
      tv: target === "tv" ? nextValues : baseline.tv.uses_defaults ? null : baseline.tv.current,
    };
  };

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        description="Choose your library roots, adjust processing rules, and confirm storage is ready."
      />

      {updateRootsMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to save folders" message={updateRootsMutation.error.message} />
      ) : null}
      {updateRulesMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to save processing rules" message={updateRulesMutation.error.message} />
      ) : null}

      <section className="dashboard-grid">
        <SectionCard title="Library folders" subtitle="Choose the main folders you want to work from.">
          <div className="list-stack">
            <div className="list-row">
              <div>
                <strong>Movies root</strong>
                <p>{roots.movies_root ?? "Not selected yet"}</p>
              </div>
              <button className="button button-primary button-small" type="button" onClick={() => setPickerTarget("movies")}>
                Choose folder
              </button>
            </div>
            <div className="list-row">
              <div>
                <strong>TV root</strong>
                <p>{roots.tv_root ?? "Not selected yet"}</p>
              </div>
              <button className="button button-primary button-small" type="button" onClick={() => setPickerTarget("tv")}>
                Choose folder
              </button>
            </div>
            <div className="info-strip">
              <strong>Media root</strong>
              <span>{roots.media_root}</span>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Storage" subtitle="Check your library and scratch paths before running jobs.">
          <KeyValueList
            items={[
              { label: "Media root", value: storage.standard_media_root },
              { label: "Media status", value: <StatusBadge value={storage.media_mounts[0]?.status ?? "unknown"} /> },
              { label: "Scratch", value: <StatusBadge value={storage.scratch.status} /> },
              { label: "Runtime", value: <StatusBadge value={runtime.status} /> },
            ]}
          />
          {storage.warnings.length > 0 ? (
            <div className="card-stack">
              {storage.warnings.map((warning) => (
                <div key={warning} className="info-strip" role="note">
                  <span>{warning}</span>
                </div>
              ))}
            </div>
          ) : null}
        </SectionCard>
      </section>

      <SectionCard title="Runtime" subtitle="A short view of the live setup.">
        <KeyValueList
          items={[
            { label: "Environment", value: runtime.environment },
            { label: "Version", value: runtime.version },
            { label: "Scratch path", value: runtime.scratch_dir },
            { label: "Data path", value: runtime.data_dir },
          ]}
        />
      </SectionCard>

      <SectionCard title="Processing rules" subtitle="Set separate defaults for films and episodes.">
        <div className="settings-rules-grid">
          <RulesetEditor
            label="Movies rules"
            rulesetKey="movies"
            ruleset={rules.movies}
            onChange={(nextValues) => {
              setRulesDraft((current) => current ? { ...current, movies: { ...current.movies, current: nextValues, uses_defaults: false } } : current);
            }}
            onSave={() => {
              if (!rulesDraft) {
                return;
              }
              updateRulesMutation.mutate(
                buildRulesPayload("movies", rulesDraft.movies.current),
                {
                  onSuccess: (data) => {
                    setPersistedRules(data);
                    setRulesDraft(data);
                  },
                },
              );
            }}
            onUseDefaults={() => {
              updateRulesMutation.mutate(
                buildRulesPayload("movies", null),
                {
                  onSuccess: (data) => {
                    setPersistedRules(data);
                    setRulesDraft(data);
                  },
                },
              );
            }}
            saving={updateRulesMutation.isPending}
          />
          <RulesetEditor
            label="TV rules"
            rulesetKey="tv"
            ruleset={rules.tv}
            onChange={(nextValues) => {
              setRulesDraft((current) => current ? { ...current, tv: { ...current.tv, current: nextValues, uses_defaults: false } } : current);
            }}
            onSave={() => {
              if (!rulesDraft) {
                return;
              }
              updateRulesMutation.mutate(
                buildRulesPayload("tv", rulesDraft.tv.current),
                {
                  onSuccess: (data) => {
                    setPersistedRules(data);
                    setRulesDraft(data);
                  },
                },
              );
            }}
            onUseDefaults={() => {
              updateRulesMutation.mutate(
                buildRulesPayload("tv", null),
                {
                  onSuccess: (data) => {
                    setPersistedRules(data);
                    setRulesDraft(data);
                  },
                },
              );
            }}
            saving={updateRulesMutation.isPending}
          />
        </div>
      </SectionCard>

      <FolderPickerModal
        open={pickerTarget !== null}
        title={pickerTarget === "movies" ? "Choose Movies folder" : "Choose TV folder"}
        initialPath={selectedRoot ?? roots.media_root}
        onClose={() => setPickerTarget(null)}
        onSelect={(path) => {
          const nextPayload =
            pickerTarget === "movies"
              ? { movies_root: path, tv_root: roots.tv_root }
              : { movies_root: roots.movies_root, tv_root: path };
          updateRootsMutation.mutate(nextPayload, {
            onSuccess: () => setPickerTarget(null),
          });
        }}
      />
    </div>
  );
}

function RulesetEditor({
  label,
  rulesetKey,
  ruleset,
  onChange,
  onSave,
  onUseDefaults,
  saving,
}: {
  label: string;
  rulesetKey: RulesetKey;
  ruleset: ProcessingRuleset;
  onChange: (values: ProcessingRuleValues) => void;
  onSave: () => void;
  onUseDefaults: () => void;
  saving: boolean;
}) {
  const isDirty = useMemo(
    () => JSON.stringify(ruleset.current) !== JSON.stringify(ruleset.defaults) || !ruleset.uses_defaults,
    [ruleset],
  );

  return (
    <div className="settings-rules-card">
      <div className="settings-rules-header">
        <div>
          <span className="metric-label">{label}</span>
          <strong>{ruleset.profile_name ?? "Default rules"}</strong>
        </div>
        <div className="badge-row">
          {ruleset.uses_defaults ? <StatusBadge value="default" /> : <StatusBadge value="custom" />}
        </div>
      </div>

      <div className="settings-rules-fields">
        <label className="field">
          <span>Target video codec</span>
          <select
            value={ruleset.current.target_video_codec}
            onChange={(event) => onChange({ ...ruleset.current, target_video_codec: event.target.value })}
          >
            {VIDEO_CODEC_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Output container</span>
          <select
            value={ruleset.current.output_container}
            onChange={(event) => onChange({ ...ruleset.current, output_container: event.target.value })}
          >
            {CONTAINER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="settings-rules-toggles">
        <ToggleField
          label="Keep English audio only"
          checked={ruleset.current.keep_english_audio_only}
          onChange={(checked) => onChange({ ...ruleset.current, keep_english_audio_only: checked })}
        />
        <ToggleField
          label="Keep forced subtitles"
          checked={ruleset.current.keep_forced_subtitles}
          onChange={(checked) => onChange({ ...ruleset.current, keep_forced_subtitles: checked })}
        />
        <ToggleField
          label="Keep one full English subtitle"
          checked={ruleset.current.keep_one_full_english_subtitle}
          onChange={(checked) => onChange({ ...ruleset.current, keep_one_full_english_subtitle: checked })}
        />
        <ToggleField
          label="Preserve surround"
          checked={ruleset.current.preserve_surround}
          onChange={(checked) => onChange({ ...ruleset.current, preserve_surround: checked })}
        />
      </div>

      <CollapsibleSection title="Advanced options" subtitle="Only change these if you need different handling.">
        <div className="settings-rules-fields">
          <ToggleField
            label="Preserve Atmos"
            checked={ruleset.current.preserve_atmos}
            onChange={(checked) => onChange({ ...ruleset.current, preserve_atmos: checked })}
          />
          <label className="field">
            <span>4K handling</span>
            <select
              value={ruleset.current.four_k_mode}
              onChange={(event) => onChange({ ...ruleset.current, four_k_mode: event.target.value })}
            >
              {FOUR_K_MODE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </CollapsibleSection>

      <div className="section-card-actions">
        <button className="button button-secondary button-small" type="button" onClick={onUseDefaults} disabled={saving}>
          Use defaults
        </button>
        <button className="button button-primary button-small" type="button" onClick={onSave} disabled={saving || !isDirty}>
          {saving ? "Saving…" : `Save ${rulesetKey === "movies" ? "movies" : "TV"} rules`}
        </button>
      </div>
    </div>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="field checkbox-field settings-toggle-field">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}
