from __future__ import annotations

from pathlib import Path

from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.probe import FFprobeClient, ProbeError
from encodr_core.verification.models import (
    VerificationCheck,
    VerificationIssue,
    VerificationOutputSummary,
    VerificationResult,
    VerificationStatus,
)
from encodr_core.verification.rules import (
    has_required_english_audio,
    has_required_subtitles,
    has_required_video,
    is_non_empty_output,
    output_container_matches,
    retains_required_4k,
    retains_required_atmos,
    retains_required_surround,
)


class OutputVerifier:
    def __init__(self, probe_client: FFprobeClient | None = None) -> None:
        self.probe_client = probe_client or FFprobeClient()

    def verify_output(
        self,
        *,
        staged_output_path: Path | str,
        plan: ProcessingPlan,
        source_media: MediaFile,
    ) -> VerificationResult:
        resolved_output = Path(staged_output_path)
        checks: list[VerificationCheck] = []
        warnings: list[VerificationIssue] = []
        failures: list[VerificationIssue] = []

        exists_and_non_empty = is_non_empty_output(resolved_output)
        checks.append(
            VerificationCheck(
                code="output_exists_and_non_empty",
                message="Staged output exists and is not empty.",
                passed=exists_and_non_empty,
                metadata={"path": resolved_output.as_posix()},
            )
        )
        if not exists_and_non_empty:
            failures.append(
                VerificationIssue(
                    code="output_missing_or_empty",
                    message="The staged output file is missing or empty.",
                    metadata={"path": resolved_output.as_posix()},
                )
            )
            return VerificationResult(
                status=VerificationStatus.FAILED,
                passed=False,
                checks=checks,
                warnings=warnings,
                failures=failures,
            )

        try:
            output_media = self.probe_client.probe_file(resolved_output)
        except ProbeError as error:
            checks.append(
                VerificationCheck(
                    code="output_probe",
                    message="Staged output could be probed successfully.",
                    passed=False,
                    metadata={"kind": error.kind},
                )
            )
            failures.append(
                VerificationIssue(
                    code="probe_failed",
                    message=error.message,
                    metadata=error.to_dict(),
                )
            )
            return VerificationResult(
                status=VerificationStatus.FAILED,
                passed=False,
                checks=checks,
                warnings=warnings,
                failures=failures,
            )

        checks.append(
            VerificationCheck(
                code="output_probe",
                message="Staged output could be probed successfully.",
                passed=True,
            )
        )

        self._add_check(
            checks,
            failures,
            code="container_matches_plan",
            message="Output container matches the plan.",
            passed=output_container_matches(output_media, plan.container.target_container),
        )
        self._add_check(
            checks,
            failures,
            code="english_audio_present",
            message="Required English audio is present in the output.",
            passed=has_required_english_audio(plan, output_media),
        )
        self._add_check(
            checks,
            failures,
            code="subtitle_intent_satisfied",
            message="Required subtitle intent is present in the output.",
            passed=has_required_subtitles(plan, output_media),
        )
        self._add_check(
            checks,
            failures,
            code="video_intent_satisfied",
            message="Output contains the expected video stream shape.",
            passed=has_required_video(plan, output_media),
        )
        self._add_check(
            checks,
            failures,
            code="four_k_preserved_when_required",
            message="4K content remains 4K where the plan requires preservation.",
            passed=retains_required_4k(source_media, plan, output_media),
        )
        self._add_check(
            checks,
            failures,
            code="surround_preserved_when_required",
            message="Required surround capability remains present.",
            passed=retains_required_surround(plan, output_media),
        )
        self._add_check(
            checks,
            failures,
            code="atmos_preserved_when_required",
            message="Required Atmos-capable audio remains present.",
            passed=retains_required_atmos(plan, output_media),
        )

        if plan.subtitles.ambiguous_forced_stream_indices:
            warnings.append(
                VerificationIssue(
                    code="ambiguous_forced_subtitle_metadata",
                    message="Forced subtitle metadata was ambiguous in the source plan.",
                    metadata={"stream_indices": plan.subtitles.ambiguous_forced_stream_indices},
                )
            )

        return VerificationResult(
            status=VerificationStatus.PASSED if not failures else VerificationStatus.FAILED,
            passed=not failures,
            checks=checks,
            warnings=warnings,
            failures=failures,
            output_summary=VerificationOutputSummary(
                file_path=output_media.file_path,
                container=output_media.extension or output_media.container.format_name,
                video_stream_count=len(output_media.video_streams),
                audio_stream_count=len(output_media.audio_streams),
                subtitle_stream_count=len(output_media.subtitle_streams),
                is_4k=output_media.is_4k,
                has_english_audio=output_media.has_english_audio,
                has_forced_english_subtitle=output_media.has_forced_english_subtitle,
                has_surround_audio=output_media.has_surround_audio,
                has_atmos_capable_audio=output_media.has_atmos_capable_audio,
                primary_video_codec=output_media.video_streams[0].codec_name if output_media.video_streams else None,
                primary_audio_codec=output_media.audio_streams[0].codec_name if output_media.audio_streams else None,
            ),
        )

    def _add_check(
        self,
        checks: list[VerificationCheck],
        failures: list[VerificationIssue],
        *,
        code: str,
        message: str,
        passed: bool,
    ) -> None:
        checks.append(
            VerificationCheck(
                code=code,
                message=message,
                passed=passed,
            )
        )
        if not passed:
            failures.append(
                VerificationIssue(
                    code=code,
                    message=message,
                )
            )
