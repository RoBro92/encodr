import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { FolderPickerModal } from "../../components/FolderPickerModal";
import { ErrorPanel } from "../../components/ErrorPanel";
import { KeyValueList } from "../../components/KeyValueList";
import { LoadingBlock } from "../../components/LoadingBlock";
import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useLibraryRootsQuery,
  useProcessingRulesQuery,
  useRuntimeStatusQuery,
  useStorageStatusQuery,
  useUpdateStatusQuery,
  useUpdateLibraryRootsMutation,
  useUpdateProcessingRulesMutation,
} from "../../lib/api/hooks";
import type {
  ProcessingRules,
  ProcessingRuleset,
  ProcessingRuleValues,
} from "../../lib/types/api";
import { APP_ROUTES } from "../../lib/utils/routes";

type PickerTarget = "movies" | "tv" | null;
type RulesetKey = "movies" | "movies_4k" | "tv" | "tv_4k";

const VIDEO_CODEC_OPTIONS = [
  { label: "H.265 / HEVC", value: "hevc" },
  { label: "H.264 / AVC", value: "h264" },
  { label: "AV1", value: "av1" },
  { label: "VP9", value: "vp9" },
  { label: "MPEG-2", value: "mpeg2" },
];

const CONTAINER_OPTIONS = [
  { label: "MKV", value: "mkv" },
  { label: "MP4", value: "mp4" },
];

const HANDLING_MODE_OPTIONS = [
  { label: "Transcode video", value: "transcode" },
  { label: "Strip only", value: "strip_only" },
  { label: "Preserve video", value: "preserve_video" },
];

const QUALITY_MODE_OPTIONS = [
  { label: "High quality", value: "high_quality" },
  { label: "Balanced", value: "balanced" },
  { label: "Efficient", value: "efficient" },
];

const COMMON_LANGUAGE_OPTIONS = ["eng", "jpn", "spa", "fra", "deu", "ita"];

const RULESET_ORDER: RulesetKey[] = ["movies", "movies_4k", "tv", "tv_4k"];

const RULESET_META: Record<RulesetKey, { title: string; summary: string }> = {
  movies: {
    title: "Movies",
    summary: "Standard film workflow for non-4K sources.",
  },
  movies_4k: {
    title: "Movies 4K",
    summary: "Separate 4K film policy with preserve-video defaults.",
  },
  tv: {
    title: "TV",
    summary: "Episode workflow for non-4K TV and anime-like series sources.",
  },
  tv_4k: {
    title: "TV 4K",
    summary: "Separate 4K TV policy for preserve or strip-only handling.",
  },
};

export function ConfigPage() {
  const [pickerTarget, setPickerTarget] = useState<PickerTarget>(null);
  const [rulesDraft, setRulesDraft] = useState<ProcessingRules | null>(null);
  const [persistedRules, setPersistedRules] = useState<ProcessingRules | null>(null);
  const rootsQuery = useLibraryRootsQuery();
  const rulesQuery = useProcessingRulesQuery();
  const runtimeQuery = useRuntimeStatusQuery();
  const storageQuery = useStorageStatusQuery();
  const updateStatusQuery = useUpdateStatusQuery();
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
    runtimeQuery.error ??
    storageQuery.error ??
    updateStatusQuery.error;
  const loading =
    rootsQuery.isLoading ||
    rulesQuery.isLoading ||
    runtimeQuery.isLoading ||
    storageQuery.isLoading ||
    updateStatusQuery.isLoading;

  if (loading) {
    return <LoadingBlock label="Loading settings" />;
  }

  if (error instanceof Error) {
    return <ErrorPanel title="Unable to load settings" message={error.message} />;
  }

  const roots = rootsQuery.data;
  const rules = rulesDraft;
  const runtime = runtimeQuery.data;
  const storage = storageQuery.data;
  const updateStatus = updateStatusQuery.data;
  if (!roots || !runtime || !storage || !rules || !updateStatus) {
    return <ErrorPanel title="Settings are unavailable" message="The API did not return settings information." />;
  }

  const selectedRoot = pickerTarget === "movies" ? roots.movies_root : roots.tv_root;
  const buildRulesPayload = (target: RulesetKey, nextValues: ProcessingRuleValues | null) => {
    const baseline = persistedRules ?? rulesQuery.data;
    if (!baseline) {
      throw new Error("Processing rules are unavailable.");
    }
    return RULESET_ORDER.reduce<Record<RulesetKey, ProcessingRuleValues | null>>((payload, key) => {
      payload[key] = key === target ? nextValues : baseline[key].uses_defaults ? null : baseline[key].current;
      return payload;
    }, { movies: null, movies_4k: null, tv: null, tv_4k: null });
  };

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        description="Choose library roots, set processing rules, and confirm runtime health."
      />

      {updateRootsMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to save folders" message={updateRootsMutation.error.message} />
      ) : null}
      {updateRulesMutation.error instanceof Error ? (
        <ErrorPanel title="Unable to save processing rules" message={updateRulesMutation.error.message} />
      ) : null}
      <section className="dashboard-grid">
        <SectionCard title="Library folders" subtitle="Choose the main folders you want Encodr to use.">
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

        <SectionCard title="Storage" subtitle="Check your media and scratch paths before you run jobs.">
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

      <SectionCard title="Runtime" subtitle="A concise view of the live runtime.">
        <KeyValueList
          items={[
            { label: "Environment", value: runtime.environment },
            { label: "Version", value: runtime.version },
            { label: "Scratch path", value: runtime.scratch_dir },
            { label: "Data path", value: runtime.data_dir },
          ]}
        />
      </SectionCard>

      <section className="dashboard-grid">
        <SectionCard
          title="Execution backends"
          subtitle="Encodr validates what this runtime can really see and what FFmpeg can actually use."
        >
          <div className="card-stack">
            <div className="info-strip">
              <strong>Operator-managed passthrough</strong>
              <span>
                Keep host-level GPU and mount passthrough managed outside Encodr. Encodr only validates what is already exposed inside this runtime.
              </span>
            </div>
            <div className="info-strip" role="note">
              <strong>Worker-level backends</strong>
              <span>
                Backend preference is now set per worker. Configure the local worker and any paired remote workers
                from the <Link to={APP_ROUTES.workers}>Workers</Link> page.
              </span>
            </div>
            <div className="status-grid">
              {runtime.execution_backends.map((backend) => (
                <article
                  key={backend.backend}
                  className={`status-card ${
                    backend.status === "degraded" || backend.status === "failed" ? "status-card-alert" : ""
                  }`}
                >
                  <div className="badge-row">
                    <StatusBadge value={backend.usable_by_ffmpeg ? "healthy" : backend.detected ? "degraded" : "failed"} />
                    <strong>{formatBackendLabel(backend.backend)}</strong>
                  </div>
                  <p className="muted-copy">{backend.message}</p>
                  <KeyValueList
                    items={[
                      { label: "Detected", value: backend.detected ? "Yes" : "No" },
                      { label: "Usable by FFmpeg", value: backend.usable_by_ffmpeg ? "Yes" : "No" },
                      { label: "Verified path", value: backend.ffmpeg_path_verified ? "Yes" : "No" },
                    ]}
                  />
                  {backend.reason_unavailable ? <p className="muted-copy">{backend.reason_unavailable}</p> : null}
                  {backend.recommended_usage ? (
                    <div className="info-strip" role="note">
                      <strong>Recommended usage</strong>
                      <span>{backend.recommended_usage}</span>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Updates" subtitle="Check what is installed and what to run from the root console.">
          <div className="card-stack">
            <div className="info-strip">
              <StatusBadge value={updateStatus.update_available ? "degraded" : "healthy"} />
              <span>
                Current {updateStatus.current_version}
                {updateStatus.latest_version ? ` • Latest ${updateStatus.latest_version}` : ""}
              </span>
            </div>
            <KeyValueList
              items={[
                { label: "Update available", value: updateStatus.update_available ? "Yes" : "No" },
                { label: "Release", value: updateStatus.release_name ?? "Not reported" },
                { label: "Check status", value: updateStatus.status },
                { label: "Command", value: <code>encodr update --apply</code> },
              ]}
            />
            {updateStatus.release_summary ? (
              <div className="info-strip" role="note">
                <strong>Summary</strong>
                <span>{updateStatus.release_summary}</span>
              </div>
            ) : null}
            {updateStatus.breaking_changes_summary ? (
              <div className="info-strip info-strip-warning" role="note">
                <strong>Breaking changes</strong>
                <span>{updateStatus.breaking_changes_summary}</span>
              </div>
            ) : null}
          </div>
        </SectionCard>
      </section>

      <SectionCard
        title="Processing rules"
        subtitle="Set separate defaults for Movies, TV, and 4K handling without editing raw config files."
      >
        <div className="settings-rules-grid settings-rules-grid-four">
          {RULESET_ORDER.map((rulesetKey) => (
            <RulesetEditor
              key={rulesetKey}
              rulesetKey={rulesetKey}
              label={RULESET_META[rulesetKey].title}
              description={RULESET_META[rulesetKey].summary}
              ruleset={rules[rulesetKey]}
              onChange={(nextValues) => {
                setRulesDraft((current) =>
                  current
                    ? {
                        ...current,
                        [rulesetKey]: { ...current[rulesetKey], current: nextValues, uses_defaults: false },
                      }
                    : current,
                );
              }}
              onSave={() => {
                if (!rulesDraft) {
                  return;
                }
                updateRulesMutation.mutate(buildRulesPayload(rulesetKey, rulesDraft[rulesetKey].current), {
                  onSuccess: (data) => {
                    setPersistedRules(data);
                    setRulesDraft(data);
                  },
                });
              }}
              onUseDefaults={() => {
                updateRulesMutation.mutate(buildRulesPayload(rulesetKey, null), {
                  onSuccess: (data) => {
                    setPersistedRules(data);
                    setRulesDraft(data);
                  },
                });
              }}
              saving={updateRulesMutation.isPending}
            />
          ))}
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

function formatBackendLabel(value: string): string {
  switch (value) {
    case "cpu":
      return "CPU";
    case "intel_igpu":
      return "Intel iGPU";
    case "nvidia_gpu":
      return "NVIDIA GPU";
    case "amd_gpu":
      return "AMD GPU";
    default:
      return value.replace(/_/g, " ");
  }
}

function RulesetEditor({
  label,
  description,
  rulesetKey,
  ruleset,
  onChange,
  onSave,
  onUseDefaults,
  saving,
}: {
  label: string;
  description: string;
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
  const summary = summariseRuleset(ruleset.current);
  const transcodeEnabled = ruleset.current.handling_mode === "transcode";

  return (
    <div className="settings-rules-card">
      <div className="settings-rules-header">
        <div className="settings-rules-heading">
          <span className="metric-label">{label}</span>
          <strong>{ruleset.profile_name ?? "Built-in defaults"}</strong>
          <p>{description}</p>
        </div>
        <div className="badge-row">
          {ruleset.uses_defaults ? <StatusBadge value="default" /> : <StatusBadge value="custom" />}
          {isFourKRuleset(rulesetKey) ? <StatusBadge value="4k" /> : <StatusBadge value="standard" />}
        </div>
      </div>

      <div className="info-strip settings-rule-summary">
        <strong>{summary.title}</strong>
        <span>{summary.body}</span>
      </div>

      <div className="settings-rules-fields settings-rules-fields-compact">
        <label className="field">
          <span>Handling mode</span>
          <select
            aria-label={`${label} handling mode`}
            value={ruleset.current.handling_mode}
            onChange={(event) => onChange({ ...ruleset.current, handling_mode: event.target.value })}
          >
            {HANDLING_MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Target video codec</span>
          <select
            aria-label={`${label} target video codec`}
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
            aria-label={`${label} output container`}
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

        <label className="field">
          <span>Quality mode</span>
          <select
            aria-label={`${label} quality mode`}
            value={ruleset.current.target_quality_mode}
            onChange={(event) => onChange({ ...ruleset.current, target_quality_mode: event.target.value })}
            disabled={!transcodeEnabled}
          >
            {QUALITY_MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Max video reduction (%)</span>
          <input
            aria-label={`${label} max video reduction`}
            type="number"
            min={0}
            max={100}
            value={ruleset.current.max_allowed_video_reduction_percent}
            onChange={(event) =>
              onChange({
                ...ruleset.current,
                max_allowed_video_reduction_percent: clampPercentage(event.target.value, ruleset.current.max_allowed_video_reduction_percent),
              })}
            disabled={!transcodeEnabled}
          />
        </label>
      </div>

      <div className="settings-rules-fields">
        <LanguageListField
          label="Preferred audio languages"
          value={ruleset.current.preferred_audio_languages}
          onChange={(languages) => onChange({ ...ruleset.current, preferred_audio_languages: languages })}
        />
        <LanguageListField
          label="Preferred subtitle languages"
          value={ruleset.current.preferred_subtitle_languages}
          onChange={(languages) => onChange({ ...ruleset.current, preferred_subtitle_languages: languages })}
        />
      </div>

      <div className="settings-rules-toggles">
        <ToggleField
          label="Keep only preferred audio languages"
          checked={ruleset.current.keep_only_preferred_audio_languages}
          onChange={(checked) => onChange({ ...ruleset.current, keep_only_preferred_audio_languages: checked })}
        />
        <ToggleField
          label="Keep forced subtitles"
          checked={ruleset.current.keep_forced_subtitles}
          onChange={(checked) => onChange({ ...ruleset.current, keep_forced_subtitles: checked })}
        />
        <ToggleField
          label="Keep one full preferred subtitle"
          checked={ruleset.current.keep_one_full_preferred_subtitle}
          onChange={(checked) => onChange({ ...ruleset.current, keep_one_full_preferred_subtitle: checked })}
        />
        <ToggleField
          label="Drop other subtitles"
          checked={ruleset.current.drop_other_subtitles}
          onChange={(checked) => onChange({ ...ruleset.current, drop_other_subtitles: checked })}
        />
      </div>

      <CollapsibleSection title="Advanced options" subtitle="Preservation controls for higher-end audio and stricter subtitle handling.">
        <div className="settings-rules-toggles">
          <ToggleField
            label="Preserve surround audio"
            checked={ruleset.current.preserve_surround}
            onChange={(checked) => onChange({ ...ruleset.current, preserve_surround: checked })}
          />
          <ToggleField
            label="Preserve 7.1 audio"
            checked={ruleset.current.preserve_seven_one}
            onChange={(checked) => onChange({ ...ruleset.current, preserve_seven_one: checked })}
          />
          <ToggleField
            label="Preserve Atmos-capable audio"
            checked={ruleset.current.preserve_atmos}
            onChange={(checked) => onChange({ ...ruleset.current, preserve_atmos: checked })}
          />
        </div>
      </CollapsibleSection>

      <div className="section-card-actions">
        <button className="button button-secondary button-small" type="button" onClick={onUseDefaults} disabled={saving}>
          Use defaults
        </button>
        <button className="button button-primary button-small" type="button" onClick={onSave} disabled={saving || !isDirty}>
          {saving ? "Saving…" : `Save ${label.toLowerCase()} rules`}
        </button>
      </div>
    </div>
  );
}

function LanguageListField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        aria-label={label}
        value={value.join(", ")}
        onChange={(event) => onChange(parseLanguageList(event.target.value))}
        placeholder="eng, jpn"
      />
      <div className="settings-language-pills" aria-hidden="true">
        {(value.length > 0 ? value : ["None selected"]).map((item) => (
          <span key={item} className="settings-language-pill">
            {item}
          </span>
        ))}
      </div>
      <div className="settings-language-shortcuts">
        {COMMON_LANGUAGE_OPTIONS.map((language) => {
          const active = value.includes(language);
          return (
            <button
              key={language}
              className={`button button-small ${active ? "button-primary" : "button-secondary"}`}
              type="button"
              onClick={() => {
                if (active) {
                  onChange(value.filter((item) => item !== language));
                  return;
                }
                onChange([...value, language]);
              }}
            >
              {language}
            </button>
          );
        })}
      </div>
    </label>
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

function isFourKRuleset(rulesetKey: RulesetKey) {
  return rulesetKey === "movies_4k" || rulesetKey === "tv_4k";
}

function parseLanguageList(raw: string) {
  return raw
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function clampPercentage(raw: string, fallback: number) {
  const parsed = Number(raw);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function summariseRuleset(values: ProcessingRuleValues) {
  const audioSummary = values.keep_only_preferred_audio_languages
    ? `${formatLanguageList(values.preferred_audio_languages)} audio only`
    : `Keep ${formatLanguageList(values.preferred_audio_languages)} plus others`;
  const subtitleSummary = values.drop_other_subtitles
    ? `${values.keep_forced_subtitles ? "forced" : "no forced"} + ${values.keep_one_full_preferred_subtitle ? "one preferred full subtitle" : "no preferred full subtitle"}`
    : "Keep additional subtitles";
  const videoSummary =
    values.handling_mode === "transcode"
      ? `${formatQualityMode(values.target_quality_mode)} transcode, max ${values.max_allowed_video_reduction_percent}% video reduction`
      : values.handling_mode === "strip_only"
        ? "Strip bloat only, keep video untouched"
        : "Preserve video stream";

  return {
    title: `${formatHandlingMode(values.handling_mode)} • ${values.target_video_codec.toUpperCase()} / ${values.output_container.toUpperCase()}`,
    body: `${audioSummary}. Subtitles: ${subtitleSummary}. ${videoSummary}.`,
  };
}

function formatLanguageList(value: string[]) {
  if (value.length === 0) {
    return "preferred";
  }
  return value.join(", ");
}

function formatHandlingMode(value: string) {
  switch (value) {
    case "strip_only":
      return "Strip only";
    case "preserve_video":
      return "Preserve video";
    default:
      return "Transcode";
  }
}

function formatQualityMode(value: string) {
  switch (value) {
    case "efficient":
      return "Efficient";
    case "balanced":
      return "Balanced";
    default:
      return "High-quality";
  }
}
