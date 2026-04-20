from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FilesystemLayout:
    root: Path
    source_dir: Path
    scratch_dir: Path
    output_dir: Path

    def create_source_file(self, relative_path: str, *, contents: str = "source") -> Path:
        file_path = self.source_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(contents, encoding="utf-8")
        return file_path


def create_filesystem_layout(tmp_path: Path) -> FilesystemLayout:
    source_dir = tmp_path / "source"
    scratch_dir = tmp_path / "scratch"
    output_dir = tmp_path / "output"
    source_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return FilesystemLayout(
        root=tmp_path,
        source_dir=source_dir,
        scratch_dir=scratch_dir,
        output_dir=output_dir,
    )
