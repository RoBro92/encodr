from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from app.services.errors import ApiValidationError
from encodr_core.config import ConfigBundle
from encodr_core.config.base import FourKMode, OutputContainer, VideoCodec
from encodr_core.config.policy import AudioRules, SubtitleRules, VideoRules
from encodr_core.config.profiles import ProfileConfig
from encodr_core.planning.rules import merge_optional_model, merge_video_rules


RulesetName = Literal["movies", "tv"]


class ProcessingRuleValues(TypedDict):
    target_video_codec: str
    output_container: str
    keep_english_audio_only: bool
    keep_forced_subtitles: bool
    keep_one_full_english_subtitle: bool
    preserve_surround: bool
    preserve_atmos: bool
    four_k_mode: str


class SetupStatePayload(TypedDict):
    movies_root: str | None
    tv_root: str | None
    processing_rules: dict[str, ProcessingRuleValues | None]


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
        payload.update({
            "movies_root": resolved_movies.as_posix() if resolved_movies is not None else None,
            "tv_root": resolved_tv.as_posix() if resolved_tv is not None else None,
        })
        self._write_state_payload(payload)
        return {
            "movies_root": payload["movies_root"],
            "tv_root": payload["tv_root"],
        }

    def get_processing_rules(self) -> dict[RulesetName, dict[str, object]]:
        payload = self._load_state_payload()
        return {
            "movies": self._build_ruleset_response("movies", payload["processing_rules"].get("movies")),
            "tv": self._build_ruleset_response("tv", payload["processing_rules"].get("tv")),
        }

    def update_processing_rules(
        self,
        *,
        movies: ProcessingRuleValues | None,
        tv: ProcessingRuleValues | None,
    ) -> dict[RulesetName, dict[str, object]]:
        payload = self._load_state_payload()
        payload["processing_rules"] = {
            "movies": self._validate_processing_rules(movies),
            "tv": self._validate_processing_rules(tv),
        }
        self._write_state_payload(payload)
        return self.get_processing_rules()

    def rules_for_source(self, source_path: str | Path) -> ProcessingRuleValues | None:
        source = Path(source_path).resolve()
        state = self._load_state_payload()
        selected_ruleset = self._resolve_ruleset_for_path(
            source,
            movies_root=state["movies_root"],
            tv_root=state["tv_root"],
        )
        if selected_ruleset is None:
            return None
        stored = state["processing_rules"].get(selected_ruleset)
        if stored is None:
            return None
        return stored

    def profile_name_for_ruleset(self, ruleset: RulesetName) -> str | None:
        return self._profile_name_for_ruleset(ruleset)

    def ruleset_for_source(self, source_path: str | Path) -> RulesetName | None:
        source = Path(source_path).resolve()
        state = self._load_state_payload()
        return self._resolve_ruleset_for_path(
            source,
            movies_root=state["movies_root"],
            tv_root=state["tv_root"],
        )

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
        return {
            "movies_root": self._clean_optional_path(raw.get("movies_root")),
            "tv_root": self._clean_optional_path(raw.get("tv_root")),
            "processing_rules": {
                "movies": self._coerce_processing_rules(
                    processing_rules.get("movies") if isinstance(processing_rules, dict) else None
                ),
                "tv": self._coerce_processing_rules(
                    processing_rules.get("tv") if isinstance(processing_rules, dict) else None
                ),
            },
        }

    def _write_state_payload(self, payload: SetupStatePayload) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _empty_payload() -> SetupStatePayload:
        return {
            "movies_root": None,
            "tv_root": None,
            "processing_rules": {
                "movies": None,
                "tv": None,
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
        return {
            "target_video_codec": video_rules.non_4k.preferred_codec.value,
            "output_container": video_rules.output_container.value,
            "keep_english_audio_only": audio_rules.keep_languages == ["eng"],
            "keep_forced_subtitles": bundle.policy.languages.preserve_forced_subtitles,
            "keep_one_full_english_subtitle": "eng" in subtitle_rules.keep_languages,
            "preserve_surround": audio_rules.preserve_best_surround,
            "preserve_atmos": audio_rules.preserve_atmos_capable,
            "four_k_mode": video_rules.four_k.mode.value,
        }

    def _profile_for_ruleset(self, ruleset: RulesetName) -> ProfileConfig | None:
        profile_name = self._profile_name_for_ruleset(ruleset)
        if not profile_name:
            return None
        return self.config_bundle.profiles.get(profile_name)

    def _profile_name_for_ruleset(self, ruleset: RulesetName) -> str | None:
        bundle = self.config_bundle
        keywords = ("movie", "movies") if ruleset == "movies" else ("tv",)
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
            four_k_mode = FourKMode(str(payload["four_k_mode"]).strip().lower()).value
        except (KeyError, ValueError) as error:
            raise ApiValidationError("Processing rules contain an unsupported value.") from error
        return {
            "target_video_codec": codec,
            "output_container": container,
            "keep_english_audio_only": bool(payload.get("keep_english_audio_only", True)),
            "keep_forced_subtitles": bool(payload.get("keep_forced_subtitles", True)),
            "keep_one_full_english_subtitle": bool(payload.get("keep_one_full_english_subtitle", True)),
            "preserve_surround": bool(payload.get("preserve_surround", True)),
            "preserve_atmos": bool(payload.get("preserve_atmos", True)),
            "four_k_mode": four_k_mode,
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
    ) -> RulesetName | None:
        for ruleset, configured_root in (("movies", movies_root), ("tv", tv_root)):
            if not configured_root:
                continue
            root = Path(configured_root).resolve()
            try:
                source_path.relative_to(root)
                return ruleset
            except ValueError:
                continue
        return None
