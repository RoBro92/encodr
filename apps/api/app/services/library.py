from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.services.errors import ApiNotFoundError, ApiValidationError
from encodr_core.config import ConfigBundle

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".mpg",
    ".mpeg",
    ".m4v",
    ".ts",
    ".m2ts",
    ".wmv",
}
EPISODE_PATTERN = re.compile(r"(s\d{1,2}e\d{1,3})|(\d{1,2}x\d{1,2})", re.IGNORECASE)
SEASON_PATTERN = re.compile(r"^season\s*\d+|^s\d{1,2}$", re.IGNORECASE)


class LibraryService:
    def __init__(self, *, config_bundle: ConfigBundle) -> None:
        self.config_bundle = config_bundle

    def allowed_roots(self) -> list[Path]:
        roots: list[Path] = []
        for mount in self.config_bundle.workers.local.media_mounts:
            try:
                resolved = mount.resolve()
            except FileNotFoundError:
                resolved = mount
            roots.append(resolved)
        return roots

    def default_root(self) -> Path:
        roots = self.allowed_roots()
        if not roots:
            raise ApiValidationError("No media mount is configured.")
        return roots[0]

    def root_for_path(self, path: Path) -> Path:
        resolved = path.resolve()
        for root in self.allowed_roots():
            try:
                resolved.relative_to(root)
                return root
            except ValueError:
                continue
        raise ApiValidationError("Folder browsing is only available under the configured media mounts.")

    def resolve_directory(self, path: str | None) -> Path:
        if path is None or not path.strip():
            candidate = self.default_root()
        else:
            candidate = Path(path).expanduser()
        if not candidate.exists():
            raise ApiNotFoundError("The selected folder does not exist.")
        if not candidate.is_dir():
            raise ApiValidationError("The selected path must be a directory.")
        resolved = candidate.resolve()
        self.root_for_path(resolved)
        return resolved

    def resolve_file(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.exists():
            raise ApiNotFoundError("The selected file does not exist.")
        if not candidate.is_file():
            raise ApiValidationError("The selected path must point to a file.")
        resolved = candidate.resolve()
        self.root_for_path(resolved)
        return resolved

    def browse_directory(self, path: str | None) -> dict[str, object]:
        current = self.resolve_directory(path)
        active_root = self.root_for_path(current)
        entries = []
        for item in sorted(current.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower())):
            if item.name.startswith("."):
                continue
            is_video = item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
            if item.is_file() and not is_video:
                continue
            entries.append(
                {
                    "name": item.name,
                    "path": item.resolve().as_posix(),
                    "entry_type": "directory" if item.is_dir() else "file",
                    "is_video": is_video,
                }
            )

        parent_path: str | None = None
        if current != active_root:
            parent = current.parent
            try:
                parent.relative_to(active_root)
                parent_path = parent.as_posix()
            except ValueError:
                parent_path = active_root.as_posix()

        return {
            "root_path": active_root.as_posix(),
            "current_path": current.as_posix(),
            "parent_path": parent_path,
            "entries": entries,
        }

    def scan_directory(self, path: str) -> dict[str, object]:
        current = self.resolve_directory(path)
        active_root = self.root_for_path(current)
        directories: list[Path] = []
        video_files: list[Path] = []
        for item in current.rglob("*"):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                directories.append(item)
                continue
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(item)

        direct_children = [child for child in current.iterdir() if child.is_dir() and not child.name.startswith(".")]
        likely_seasons = sum(1 for directory in directories if SEASON_PATTERN.search(directory.name))
        likely_episodes = sum(1 for file_path in video_files if EPISODE_PATTERN.search(file_path.name))
        likely_films = max(len(video_files) - likely_episodes, 0)
        likely_shows = sum(
            1
            for directory in direct_children
            if not SEASON_PATTERN.search(directory.name)
        )

        file_items = [
            {
                "name": file_path.name,
                "path": file_path.as_posix(),
                "entry_type": "file",
                "is_video": True,
            }
            for file_path in sorted(video_files, key=lambda item: item.as_posix().lower())
        ]

        return {
            "folder_path": current.as_posix(),
            "root_path": active_root.as_posix(),
            "directory_count": len(directories),
            "direct_directory_count": len(direct_children),
            "video_file_count": len(video_files),
            "likely_show_count": likely_shows,
            "likely_season_count": likely_seasons,
            "likely_episode_count": likely_episodes,
            "likely_film_count": likely_films,
            "files": file_items,
        }

    def resolve_selection(
        self,
        *,
        source_path: str | None = None,
        folder_path: str | None = None,
        selected_paths: list[str] | None = None,
    ) -> tuple[str, list[Path]]:
        selected_paths = selected_paths or []
        provided = sum(bool(value) for value in [source_path, folder_path, selected_paths])
        if provided != 1:
            raise ApiValidationError("Provide exactly one of source_path, folder_path, or selected_paths.")

        if source_path:
            return "file", [self.resolve_file(source_path)]

        if folder_path:
            scan = self.scan_directory(folder_path)
            files = [self.resolve_file(item["path"]) for item in scan["files"]]
            return "folder", files

        resolved_files = [self.resolve_file(path) for path in selected_paths]
        deduplicated: dict[str, Path] = {path.as_posix(): path for path in resolved_files}
        if not deduplicated:
            raise ApiValidationError("No file paths were selected.")
        return "selection", list(deduplicated.values())

    @staticmethod
    def summarise_actions(actions: list[str]) -> list[dict[str, object]]:
        counts = Counter(actions)
        return [
            {"value": action, "count": count}
            for action, count in sorted(counts.items(), key=lambda item: item[0])
        ]
