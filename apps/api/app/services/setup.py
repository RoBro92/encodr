from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, TypedDict

from app.services.errors import ApiValidationError
from encodr_core.config import ConfigBundle
from encodr_core.config.base import (
    FourKMode,
    OutputContainer,
    RuleHandlingMode,
    VideoCodec,
    VideoQualityMode,
    deduplicate_preserving_order,
)
from encodr_core.config.policy import AudioRules, SubtitleRules, VideoRules
from encodr_core.config.profiles import ProfileConfig
from encodr_core.planning.rules import merge_optional_model, merge_video_rules

LANGUAGE_CODE_RE = re.compile(r"^[a-z]{3}$")

RulesetName = Literal["movies", "movies_4k", "tv", "tv_4k"]
ExecutionBackendPreference = Literal["cpu_only", "prefer_intel_igpu", "prefer_nvidia_gpu", "prefer_amd_gpu"]


class ProcessingRuleValues(TypedDict):
    target_video_codec: str
    output_container: str
    preferred_audio_languages: list[str]
    keep_only_preferred_audio_languages: bool
    preserve_surround: bool
    preserve_seven_one: bool
    preserve_atmos: bool
    preferred_subtitle_languages: list[str]
    keep_forced_subtitles: bool
    keep_one_full_preferred_subtitle: bool
    drop_other_subtitles: bool
    handling_mode: str
    target_quality_mode: str
    max_allowed_video_reduction_percent: int


class SetupStatePayload(TypedDict):
    movies_root: str | None
    tv_root: str | None
    processing_rules: dict[str, ProcessingRuleValues | None]
    execution_preferences: dict[str, object]


class SetupStateService:
    def __init__(self, *, config_bundle: ConfigBundle) -> None:
        self.config_bundle = config_bundle
        self.state_path = self.config_bundle.app.data_dir / "setup-state.json"

    def get_state(self) -> dict[str, str | None]:
        payload = self._load_state_payload()
        return {
            "movies_root": payload["movies_root"],
            "tv_root": payload["tv_root"],
        }

    def update_state(
        self,
        *,
        movies_root: str | None,
        tv_root: str | None,
        allowed_roots: list[Path],
    ) -> dict[str, str | None]:
        resolved_movies = self._validate_optional_path(movies_root, allowed_roots=allowed_roots)
        resolved_tv = self._validate_optional_path(tv_root, allowed_roots=allowed_roots)
        payload = self._load_state_payload()
        payload.update(
            {
                "movies_root": resolved_movies.as_posix() if resolved_movies is not None else None,
                "tv_root": resolved_tv.as_posix() if resolved_tv is not None else None,
            }
        )
        self._write_state_payload(payload)
        return {
            "movies_root": payload["movies_root"],
            "tv_root": payload["tv_root"],
        }

    def get_processing_rules(self) -> dict[RulesetName, dict[str, object]]:
        payload = self._load_state_payload()
        return {
            ruleset: self._build_ruleset_response(ruleset, payload["processing_rules"].get(ruleset))
            for ruleset in self._ruleset_names()
        }

    def get_execution_preferences(self) -> dict[str, object]:
        payload = self._load_state_payload()
        return dict(payload["execution_preferences"])

    def update_processing_rules(
        self,
        *,
        movies: ProcessingRuleValues | None,
        movies_4k: ProcessingRuleValues | None,
        tv: ProcessingRuleValues | None,
        tv_4k: ProcessingRuleValues | None,
    ) -> dict[RulesetName, dict[str, object]]:
        payload = self._load_state_payload()
        payload["processing_rules"] = {
            "movies": self._validate_processing_rules(movies),
            "movies_4k": self._validate_processing_rules(movies_4k),
            "tv": self._validate_processing_rules(tv),
            "tv_4k": self._validate_processing_rules(tv_4k),
        }
        self._write_state_payload(payload)
        return self.get_processing_rules()

    def update_execution_preferences(
        self,
        *,
        preferred_backend: ExecutionBackendPreference,
        allow_cpu_fallback: bool,
    ) -> dict[str, object]:
        if preferred_backend not in {
            "cpu_only",
            "prefer_intel_igpu",
            "prefer_nvidia_gpu",
            "prefer_amd_gpu",
        }:
            raise ApiValidationError("Unsupported execution backend preference.")
        payload = self._load_state_payload()
        payload["execution_preferences"] = {
            "preferred_backend": preferred_backend,
            "allow_cpu_fallback": bool(allow_cpu_fallback),
        }
        self._write_state_payload(payload)
        return dict(payload["execution_preferences"])

    def rules_for_source(self, source_path: str | Path, *, is_4k: bool = False) -> ProcessingRuleValues | None:
        source = Path(source_path).resolve()
        state = self._load_state_payload()
        selected_ruleset = self._resolve_ruleset_for_path(
            source,
            movies_root=state["movies_root"],
            tv_root=state["tv_root"],
            is_4k=is_4k,
        )
        if selected_ruleset is None:
            return None
        return state["processing_rules"].get(selected_ruleset)

    def rules_for_ruleset(self, ruleset: RulesetName) -> ProcessingRuleValues | None:
        state = self._load_state_payload()
        return state["processing_rules"].get(ruleset)

    def profile_name_for_ruleset(self, ruleset: RulesetName) -> str | None:
        return self._profile_name_for_ruleset(ruleset)

    def ruleset_for_source(self, source_path: str | Path, *, is_4k: bool = False) -> RulesetName | None:
        source = Path(source_path).resolve()
        state = self._load_state_payload()
        return self._resolve_ruleset_for_path(
            source,
            movies_root=state["movies_root"],
            tv_root=state["tv_root"],
            is_4k=is_4k,
        )

    @staticmethod
    def _ruleset_names() -> tuple[RulesetName, RulesetName, RulesetName, RulesetName]:
        return ("movies", "movies_4k", "tv", "tv_4k")

    @staticmethod
    def _clean_optional_path(value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _validate_optional_path(value: str | None, *, allowed_roots: list[Path]) -> Path | None:
        if value is None or not value.strip():
            return None
        candidate = Path(value).expanduser()
        if not candidate.exists():
            raise ApiValidationError("Selected root path does not exist.")
        if not candidate.is_dir():
            raise ApiValidationError("Selected root path must be a directory.")
        resolved = candidate.resolve()
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        raise ApiValidationError("Selected root path must stay under the configured media mount.")

    def _load_state_payload(self) -> SetupStatePayload:
        if not self.state_path.exists():
            return self._empty_payload()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self._empty_payload()
        processing_rules = raw.get("processing_rules")
        payload = self._empty_payload()
        payload["movies_root"] = self._clean_optional_path(raw.get("movies_root"))
        payload["tv_root"] = self._clean_optional_path(raw.get("tv_root"))
        execution_preferences = raw.get("execution_preferences")
        if isinstance(execution_preferences, dict):
            preferred_backend = str(execution_preferences.get("preferred_backend") or "cpu_only").strip()
            if preferred_backend not in {
                "cpu_only",
                "prefer_intel_igpu",
                "prefer_nvidia_gpu",
                "prefer_amd_gpu",
            }:
                preferred_backend = "cpu_only"
            payload["execution_preferences"] = {
                "preferred_backend": preferred_backend,
                "allow_cpu_fallback": bool(execution_preferences.get("allow_cpu_fallback", True)),
            }
        if isinstance(processing_rules, dict):
            for ruleset in self._ruleset_names():
                payload["processing_rules"][ruleset] = self._coerce_processing_rules(processing_rules.get(ruleset))
            # Migrate legacy two-ruleset state without fabricating 4K overrides.
            if payload["processing_rules"]["movies"] is None:
                payload["processing_rules"]["movies"] = self._coerce_processing_rules(processing_rules.get("movies"))
            if payload["processing_rules"]["tv"] is None:
                payload["processing_rules"]["tv"] = self._coerce_processing_rules(processing_rules.get("tv"))
        return payload

    def _write_state_payload(self, payload: SetupStatePayload) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def _empty_payload(cls) -> SetupStatePayload:
        return {
            "movies_root": None,
            "tv_root": None,
            "processing_rules": {ruleset: None for ruleset in cls._ruleset_names()},
            "execution_preferences": {
                "preferred_backend": "cpu_only",
                "allow_cpu_fallback": True,
            },
        }

    def _build_ruleset_response(
        self,
        ruleset: RulesetName,
        stored: ProcessingRuleValues | None,
    ) -> dict[str, object]:
        defaults = self._default_processing_rules(ruleset)
        return {
            "profile_name": self._profile_name_for_ruleset(ruleset),
            "current": stored or defaults,
            "defaults": defaults,
            "uses_defaults": stored is None,
        }

    def _default_processing_rules(self, ruleset: RulesetName) -> ProcessingRuleValues:
        bundle = self.config_bundle
        profile = self._profile_for_ruleset(ruleset)
        audio_rules: AudioRules = merge_optional_model(bundle.policy.audio, profile.audio if profile else None)
        subtitle_rules: SubtitleRules = merge_optional_model(
            bundle.policy.subtitles,
            profile.subtitles if profile else None,
        )
        video_rules: VideoRules = merge_video_rules(bundle.policy.video, profile.video if profile else None)
        is_4k_ruleset = ruleset.endswith("_4k")
        video_defaults = video_rules.four_k if is_4k_ruleset else video_rules.non_4k
        target_codec = video_rules.four_k.preferred_codec.value if is_4k_ruleset else video_rules.non_4k.preferred_codec.value
        quality_mode = video_defaults.quality_mode.value
        max_reduction = video_defaults.max_video_reduction_percent
        if is_4k_ruleset:
            handling_mode = (
                RuleHandlingMode.TRANSCODE.value
                if video_rules.four_k.allow_transcode and video_rules.four_k.mode != FourKMode.STRIP_ONLY
                else RuleHandlingMode.PRESERVE_VIDEO.value
            )
        else:
            handling_mode = (
                RuleHandlingMode.TRANSCODE.value
                if video_rules.non_4k.allow_transcode
                else RuleHandlingMode.STRIP_ONLY.value
            )
        return {
            "target_video_codec": target_codec,
            "output_container": video_rules.output_container.value,
            "preferred_audio_languages": list(audio_rules.keep_languages),
            "keep_only_preferred_audio_languages": audio_rules.keep_only_preferred_languages,
            "preserve_surround": audio_rules.preserve_best_surround,
            "preserve_seven_one": audio_rules.preserve_seven_one,
            "preserve_atmos": audio_rules.preserve_atmos_capable,
            "preferred_subtitle_languages": list(subtitle_rules.keep_languages),
            "keep_forced_subtitles": bundle.policy.languages.preserve_forced_subtitles,
            "keep_one_full_preferred_subtitle": subtitle_rules.keep_one_full_preferred_subtitle,
            "drop_other_subtitles": subtitle_rules.drop_other_subtitles,
            "handling_mode": handling_mode,
            "target_quality_mode": quality_mode,
            "max_allowed_video_reduction_percent": max_reduction,
        }

    def _profile_for_ruleset(self, ruleset: RulesetName) -> ProfileConfig | None:
        profile_name = self._profile_name_for_ruleset(ruleset)
        if not profile_name:
            return None
        return self.config_bundle.profiles.get(profile_name)

    def _profile_name_for_ruleset(self, ruleset: RulesetName) -> str | None:
        bundle = self.config_bundle
        base_ruleset = "movies" if ruleset.startswith("movies") else "tv"
        keywords = ("movie", "movies") if base_ruleset == "movies" else ("tv",)
        for override in bundle.policy.profiles.path_overrides:
            prefix_text = override.path_prefix.lower()
            if any(keyword in prefix_text for keyword in keywords):
                return override.profile
        for name in bundle.profiles:
            lowered = name.lower()
            if any(keyword in lowered for keyword in keywords):
                return name
        return None

    def _validate_processing_rules(self, payload: ProcessingRuleValues | None) -> ProcessingRuleValues | None:
        if payload is None:
            return None
        try:
            codec = VideoCodec(str(payload["target_video_codec"]).strip().lower()).value
            container = OutputContainer(str(payload["output_container"]).strip().lower()).value
            handling_mode = RuleHandlingMode(str(payload["handling_mode"]).strip().lower()).value
            quality_mode = VideoQualityMode(str(payload["target_quality_mode"]).strip().lower()).value
        except (KeyError, ValueError) as error:
            raise ApiValidationError("Processing rules contain an unsupported value.") from error

        preferred_audio_languages = self._validate_language_list(payload.get("preferred_audio_languages"))
        preferred_subtitle_languages = self._validate_language_list(payload.get("preferred_subtitle_languages"))
        max_reduction = int(payload.get("max_allowed_video_reduction_percent", 0))
        if max_reduction < 0 or max_reduction > 95:
            raise ApiValidationError("Maximum allowed video reduction must be between 0 and 95.")

        return {
            "target_video_codec": codec,
            "output_container": container,
            "preferred_audio_languages": preferred_audio_languages,
            "keep_only_preferred_audio_languages": bool(payload.get("keep_only_preferred_audio_languages", True)),
            "preserve_surround": bool(payload.get("preserve_surround", True)),
            "preserve_seven_one": bool(payload.get("preserve_seven_one", True)),
            "preserve_atmos": bool(payload.get("preserve_atmos", True)),
            "preferred_subtitle_languages": preferred_subtitle_languages,
            "keep_forced_subtitles": bool(payload.get("keep_forced_subtitles", True)),
            "keep_one_full_preferred_subtitle": bool(payload.get("keep_one_full_preferred_subtitle", True)),
            "drop_other_subtitles": bool(payload.get("drop_other_subtitles", True)),
            "handling_mode": handling_mode,
            "target_quality_mode": quality_mode,
            "max_allowed_video_reduction_percent": max_reduction,
        }

    def _coerce_processing_rules(self, value: object) -> ProcessingRuleValues | None:
        if not isinstance(value, dict):
            return None
        try:
            return self._validate_processing_rules(value)  # type: ignore[arg-type]
        except ApiValidationError:
            return None

    @staticmethod
    def _resolve_ruleset_for_path(
        source_path: Path,
        *,
        movies_root: str | None,
        tv_root: str | None,
        is_4k: bool,
    ) -> RulesetName | None:
        matches: list[tuple[int, str]] = []
        for base_ruleset, configured_root in (("movies", movies_root), ("tv", tv_root)):
            if not configured_root:
                continue
            root = Path(configured_root).resolve()
            try:
                source_path.relative_to(root)
                matches.append((len(root.as_posix()), base_ruleset))
            except ValueError:
                continue
        if not matches:
            return None
        matches.sort(reverse=True)
        base_ruleset = matches[0][1]
        return f"{base_ruleset}_4k" if is_4k else base_ruleset  # type: ignore[return-value]

    @staticmethod
    def _validate_language_list(value: object) -> list[str]:
        if not isinstance(value, list):
            raise ApiValidationError("Language preferences must be provided as a list.")
        cleaned = []
        for item in value:
            code = str(item).strip().lower()
            if not LANGUAGE_CODE_RE.match(code):
                raise ApiValidationError("Language preferences must use three-letter language codes.")
            cleaned.append(code)
        deduplicated = deduplicate_preserving_order(cleaned)
        if not deduplicated:
            raise ApiValidationError("At least one preferred language is required.")
        return deduplicated
