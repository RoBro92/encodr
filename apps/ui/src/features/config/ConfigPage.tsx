import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";

import { FolderPickerModal } from "../../components/FolderPickerModal";
import { ErrorPanel } from "../../components/ErrorPanel";
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
  const [isChangelogModalOpen, setIsChangelogModalOpen] = useState(false);
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
      <section className="settings-overview-grid">
        <div className="settings-overview-item">
          <SectionCard title="Library folders" subtitle="Choose the main folders you want Encodr to use.">
            <div className="settings-folder-list">
              <div className="settings-folder-row">
                <div>
                  <strong>Movies root</strong>
                  <p>{roots.movies_root ?? "Not selected yet"}</p>
                </div>
                <button className="button button-primary button-small" type="button" onClick={() => setPickerTarget("movies")}>
                  Choose folder
                </button>
              </div>
              <div className="settings-folder-row">
                <div>
                  <strong>TV root</strong>
                  <p>{roots.tv_root ?? "Not selected yet"}</p>
                </div>
                <button className="button button-primary button-small" type="button" onClick={() => setPickerTarget("tv")}>
                  Choose folder
                </button>
              </div>
              <div className="settings-folder-row settings-folder-row-readonly">
                <div>
                  <strong>Media root</strong>
                  <p>{roots.media_root}</p>
                </div>
              </div>
            </div>
          </SectionCard>
        </div>

        <div className="settings-overview-item settings-overview-item-storage">
          <SectionCard title="Storage" subtitle="Check your media and scratch paths before you run jobs.">
            <div className="settings-storage-stack">
              <div className="settings-data-grid settings-data-grid-storage">
                <SettingsDataItem label="Runtime health" value={<StatusBadge value={runtime.status} />} />
                <SettingsDataItem label="Environment" value={runtime.environment} />
                <SettingsDataItem label="Version" value={runtime.version} />
                <SettingsDataItem label="Media root" value={storage.standard_media_root} />
                <SettingsDataItem label="Media status" value={<StatusBadge value={storage.media_mounts[0]?.status ?? "unknown"} />} />
                <SettingsDataItem label="Scratch path" value={runtime.scratch_dir} />
                <SettingsDataItem label="Scratch status" value={<StatusBadge value={storage.scratch.status} />} />
                <SettingsDataItem label="Data path" value={runtime.data_dir} />
              </div>
              {storage.warnings.length > 0 ? (
                <div className="settings-warning-stack">
                  {storage.warnings.map((warning) => (
                    <div key={warning} className="info-strip info-strip-warning settings-warning-callout" role="note">
                      <span>{warning}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </SectionCard>
        </div>

        <div className="settings-overview-item">
          <SectionCard title="Updates" subtitle="Check what is installed and what to run from the root console.">
            <div className="settings-updates-stack">
              <div className="info-strip">
                <StatusBadge value={updateStatus.update_available ? "degraded" : "healthy"} />
                <span>
                  Current {updateStatus.current_version}
                  {updateStatus.latest_version ? ` • Latest ${updateStatus.latest_version}` : ""}
                </span>
              </div>
              <div className="settings-data-grid settings-data-grid-updates">
                <SettingsDataItem label="Update available" value={updateStatus.update_available ? "Yes" : "No"} />
                <SettingsDataItem label="Release" value={updateStatus.release_name ?? "Not reported"} />
                <SettingsDataItem label="Check status" value={updateStatus.status} />
                <SettingsDataItem label="Command" value={<code className="settings-command-code">encodr update --apply</code>} />
              </div>
              <div className="settings-updates-actions">
                <button className="button button-secondary button-small" type="button" onClick={() => setIsChangelogModalOpen(true)}>
                  View changelog
                </button>
              </div>
            </div>
          </SectionCard>
        </div>
      </section>

      {isChangelogModalOpen ? (
        <ChangelogModal
          releaseName={updateStatus.release_name}
          releaseSummary={updateStatus.release_summary}
          breakingChangesSummary={updateStatus.breaking_changes_summary}
          onClose={() => setIsChangelogModalOpen(false)}
        />
      ) : null}

      <ProcessingRulesSection
        rules={rules}
        persistedRules={persistedRules ?? rules}
        onRulesetChange={(rulesetKey, nextValues) => {
          setRulesDraft((current) =>
            current
              ? {
                  ...current,
                  [rulesetKey]: { ...current[rulesetKey], current: nextValues, uses_defaults: false },
                }
              : current,
          );
        }}
        onRulesetSave={(rulesetKey) => {
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
        onRulesetUseDefaults={(rulesetKey) => {
          updateRulesMutation.mutate(buildRulesPayload(rulesetKey, null), {
            onSuccess: (data) => {
              setPersistedRules(data);
              setRulesDraft(data);
            },
          });
        }}
        saving={updateRulesMutation.isPending}
      />

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

function ChangelogModal({
  releaseName,
  releaseSummary,
  breakingChangesSummary,
  onClose,
}: {
  releaseName: string | null;
  releaseSummary: string | null;
  breakingChangesSummary: string | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const markdown = [
    releaseSummary ?? "No release notes were reported for this update.",
    breakingChangesSummary ? `\n\n## Breaking changes\n\n${breakingChangesSummary}` : "",
  ].join("");

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus();
    };
  }, []);

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }

    if (event.key !== "Tab" || !dialogRef.current) {
      return;
    }

    const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length === 0) {
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const activeElement = document.activeElement;
    if (event.shiftKey && activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      className="modal-backdrop changelog-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      onKeyDown={handleKeyDown}
    >
      <section
        ref={dialogRef}
        className="modal-panel changelog-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="changelog-modal-title"
      >
        <div className="changelog-modal-header">
          <div>
            <p className="section-eyebrow">{releaseName ?? "Encodr changelog"}</p>
            <h2 id="changelog-modal-title">Release Notes</h2>
          </div>
          <button ref={closeButtonRef} className="button button-secondary button-small" type="button" onClick={onClose} aria-label="Close release notes">
            X
          </button>
        </div>
        <div className="changelog-markdown">
          <MarkdownContent source={markdown} />
        </div>
        <div className="changelog-modal-footer">
          <button className="button button-primary button-small" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </section>
    </div>
  );
}

function SettingsDataItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="settings-data-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MarkdownContent({ source }: { source: string }) {
  const blocks = parseMarkdownBlocks(source);
  return (
    <>
      {blocks.map((block, index) => {
        const key = `${block.type}-${index}`;
        switch (block.type) {
          case "heading":
            return block.level === 2 ? (
              <h2 key={key}>{renderInlineMarkdown(block.text)}</h2>
            ) : block.level === 3 ? (
              <h3 key={key}>{renderInlineMarkdown(block.text)}</h3>
            ) : (
              <h4 key={key}>{renderInlineMarkdown(block.text)}</h4>
            );
          case "list":
            return block.ordered ? (
              <ol key={key}>
                {block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>)}
              </ol>
            ) : (
              <ul key={key}>
                {block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>)}
              </ul>
            );
          default:
            return <p key={key}>{renderInlineMarkdown(block.text)}</p>;
        }
      })}
    </>
  );
}

type MarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; text: string };

function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let listOrdered = false;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({ type: "list", ordered: listOrdered, items: listItems });
      listItems = [];
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: Math.max(2, heading[1].length), text: heading[2] });
      continue;
    }

    const unorderedList = trimmed.match(/^[-*]\s+(.+)$/);
    const orderedList = trimmed.match(/^\d+\.\s+(.+)$/);
    if (unorderedList || orderedList) {
      flushParagraph();
      const ordered = Boolean(orderedList);
      if (listItems.length > 0 && ordered !== listOrdered) {
        flushList();
      }
      listOrdered = ordered;
      listItems.push((orderedList ?? unorderedList)![1]);
      continue;
    }

    flushList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  return blocks.length > 0 ? blocks : [{ type: "paragraph", text: "No release notes were reported for this update." }];
}

function renderInlineMarkdown(source: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  let lastIndex = 0;
  for (const match of source.matchAll(pattern)) {
    const matchIndex = match.index ?? 0;
    if (matchIndex > lastIndex) {
      nodes.push(source.slice(lastIndex, matchIndex));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={matchIndex}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={matchIndex}>{token.slice(2, -2)}</strong>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      nodes.push(link ? <a key={matchIndex} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a> : token);
    }
    lastIndex = matchIndex + token.length;
  }
  if (lastIndex < source.length) {
    nodes.push(source.slice(lastIndex));
  }
  return nodes;
}

function ProcessingRulesSection({
  rules,
  persistedRules,
  onRulesetChange,
  onRulesetSave,
  onRulesetUseDefaults,
  saving,
}: {
  rules: ProcessingRules;
  persistedRules: ProcessingRules;
  onRulesetChange: (rulesetKey: RulesetKey, values: ProcessingRuleValues) => void;
  onRulesetSave: (rulesetKey: RulesetKey) => void;
  onRulesetUseDefaults: (rulesetKey: RulesetKey) => void;
  saving: boolean;
}) {
  const [activeTab, setActiveTab] = useState<RulesetKey>("movies");
  const activeRuleset = rules[activeTab];
  const activePersistedRuleset = persistedRules[activeTab];

  return (
    <SectionCard
      title="Processing rules"
      subtitle="Set separate defaults for Movies, TV, and 4K handling without editing raw config files."
    >
      <div className="settings-rules-shell" data-testid="processing-rules-section">
        <div className="settings-rules-tabs" role="tablist" aria-label="Processing rulesets">
          {RULESET_ORDER.map((rulesetKey) => {
            const selected = activeTab === rulesetKey;
            const persistedRuleset = persistedRules[rulesetKey];
            const badgeLabel = persistedRuleset.uses_defaults ? "Default" : "Custom";
            return (
              <button
                key={rulesetKey}
                id={`processing-rules-tab-${rulesetKey}`}
                className={`settings-rules-tab ${selected ? "settings-rules-tab-active" : ""}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`processing-rules-panel-${rulesetKey}`}
                data-testid={`processing-rules-tab-${rulesetKey}`}
                onClick={() => setActiveTab(rulesetKey)}
              >
                <span>
                  <strong>{RULESET_META[rulesetKey].title}</strong>
                  <small>{isFourKRuleset(rulesetKey) ? "4K policy" : "Standard policy"}</small>
                </span>
                <span
                  className={`settings-rules-tab-badge ${
                    persistedRuleset.uses_defaults ? "settings-rules-tab-badge-default" : "settings-rules-tab-badge-custom"
                  }`}
                >
                  {badgeLabel}
                </span>
              </button>
            );
          })}
        </div>

        <div
          id={`processing-rules-panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`processing-rules-tab-${activeTab}`}
          data-testid={`processing-rules-editor-${activeTab}`}
        >
          <RulesetEditor
            rulesetKey={activeTab}
            label={RULESET_META[activeTab].title}
            description={RULESET_META[activeTab].summary}
            ruleset={activeRuleset}
            persistedRuleset={activePersistedRuleset}
            onChange={(nextValues) => onRulesetChange(activeTab, nextValues)}
            onSave={() => onRulesetSave(activeTab)}
            onUseDefaults={() => onRulesetUseDefaults(activeTab)}
            saving={saving}
          />
        </div>
      </div>
    </SectionCard>
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
  persistedRuleset,
  onChange,
  onSave,
  onUseDefaults,
  saving,
}: {
  label: string;
  description: string;
  rulesetKey: RulesetKey;
  ruleset: ProcessingRuleset;
  persistedRuleset: ProcessingRuleset;
  onChange: (values: ProcessingRuleValues) => void;
  onSave: () => void;
  onUseDefaults: () => void;
  saving: boolean;
}) {
  const isDirty = useMemo(
    () =>
      JSON.stringify(ruleset.current) !== JSON.stringify(persistedRuleset.current) ||
      ruleset.uses_defaults !== persistedRuleset.uses_defaults,
    [persistedRuleset, ruleset],
  );
  const summary = summariseRuleset(ruleset.current);
  const transcodeEnabled = ruleset.current.handling_mode === "transcode";

  return (
    <div className="settings-rules-editor">
      <div className="settings-rules-editor-header">
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

      <div className="settings-rules-summary-banner">
        <span className="settings-rules-summary-icon" aria-hidden="true">
          i
        </span>
        <div>
          <strong>{summary.title}</strong>
          <span>{summary.body}</span>
        </div>
      </div>

      <div className="settings-rules-form-card">
        <div className="settings-rules-form-card-header">
          <h3>Video pipeline</h3>
          <p>Choose the primary handling path and output format.</p>
        </div>
        <div className="settings-rules-fields settings-rules-fields-three">
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
        </div>
      </div>

      <div className={`settings-rules-form-card settings-rules-quality-card ${transcodeEnabled ? "" : "settings-rules-card-disabled"}`}>
        <div className="settings-rules-form-card-header">
          <h3>Quality limits</h3>
          <p>{transcodeEnabled ? "Tune transcode quality and safety boundaries." : "Only available when handling mode is set to transcode."}</p>
        </div>
        <div className="settings-rules-fields settings-rules-fields-two">
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
      </div>

      <div className="settings-rules-form-card">
        <div className="settings-rules-form-card-header">
          <h3>Language and subtitle matrix</h3>
          <p>Set the audio and subtitle language policy for this ruleset.</p>
        </div>
        <div className="settings-rules-language-matrix">
          <div className="settings-rules-language-column">
            <div className="settings-rules-column-heading">
              <h4>Audio</h4>
              <p>Preferred audio tracks and cleanup rules.</p>
            </div>
            <LanguageListField
              label="Preferred audio languages"
              value={ruleset.current.preferred_audio_languages}
              onChange={(languages) => onChange({ ...ruleset.current, preferred_audio_languages: languages })}
            />
            <ToggleField
              label="Keep only preferred audio languages"
              checked={ruleset.current.keep_only_preferred_audio_languages}
              onChange={(checked) => onChange({ ...ruleset.current, keep_only_preferred_audio_languages: checked })}
            />
          </div>

          <div className="settings-rules-language-column settings-rules-language-column-divided">
            <div className="settings-rules-column-heading">
              <h4>Subtitles</h4>
              <p>Forced, full, and non-preferred subtitle behavior.</p>
            </div>
            <LanguageListField
              label="Preferred subtitle languages"
              value={ruleset.current.preferred_subtitle_languages}
              onChange={(languages) => onChange({ ...ruleset.current, preferred_subtitle_languages: languages })}
            />
            <div className="settings-rules-toggles">
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
          </div>
        </div>
      </div>

      <details className="settings-rules-advanced">
        <summary>
          <span>Advanced audio preservation</span>
          <small>Surround, 7.1, and Atmos-capable tracks</small>
        </summary>
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
      </details>

      <div className="settings-rules-action-footer">
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
              aria-pressed={active}
              onClick={() => onChange(appendLanguage(value, language))}
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

function appendLanguage(value: string[], language: string) {
  const normalised = parseLanguageList([...value, language].join(", "));
  return Array.from(new Set(normalised));
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
