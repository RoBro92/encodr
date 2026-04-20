from __future__ import annotations

import subprocess
from pathlib import Path

from encodr_core.media.models import MediaFile
from encodr_core.probe.errors import ProbeBinaryNotFoundError, ProbeProcessError
from encodr_core.probe.parser import parse_ffprobe_json_output


class FFprobeClient:
    def __init__(self, binary_path: Path | str = "/usr/bin/ffprobe") -> None:
        self.binary_path = Path(binary_path)

    def build_command(self, file_path: Path | str) -> list[str]:
        return [
            str(self.binary_path),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(file_path),
        ]

    def probe_file(self, file_path: Path | str) -> MediaFile:
        resolved_path = Path(file_path)
        command = self.build_command(resolved_path)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise ProbeBinaryNotFoundError(
                binary_path=self.binary_path,
                file_path=resolved_path,
            ) from error

        if result.returncode != 0:
            raise ProbeProcessError(
                file_path=resolved_path,
                binary_path=self.binary_path,
                exit_code=result.returncode,
                stderr=(result.stderr or "").strip() or None,
            )

        return parse_ffprobe_json_output(result.stdout, file_path=resolved_path)

