from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

from app.services.errors import ApiValidationError
from encodr_core.config import ConfigBundle
from encodr_shared import normalise_path_mappings


_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_PATH_KEY_NAMES = {
    "path",
    "source_path",
    "staged_output_path",
    "output_path",
    "final_output_path",
    "original_backup_path",
    "backup_path",
}


@dataclass(frozen=True, slots=True)
class PathRoots:
    media: tuple[Path, ...]
    scratch: tuple[Path, ...]
    backup: tuple[Path, ...]

    @property
    def output(self) -> tuple[Path, ...]:
        return _deduplicate_paths((*self.media, *self.scratch))

    @property
    def replacement_payload(self) -> tuple[Path, ...]:
        return _deduplicate_paths((*self.media, *self.scratch, *self.backup))


def configured_path_roots(config_bundle: ConfigBundle) -> PathRoots:
    media_roots = tuple(Path(path) for path in config_bundle.workers.local.media_mounts)
    scratch_roots = _deduplicate_paths(
        (
            Path(config_bundle.app.scratch_dir),
            Path(config_bundle.workers.local.scratch_dir),
        )
    )
    return PathRoots(
        media=_deduplicate_paths(media_roots),
        scratch=scratch_roots,
        backup=_deduplicate_paths(media_roots),
    )


def path_roots_with_extra_scratch_roots(roots: PathRoots, extra_roots: Iterable[Path | str]) -> PathRoots:
    return PathRoots(
        media=roots.media,
        scratch=_deduplicate_paths((*roots.scratch, *(Path(path) for path in extra_roots))),
        backup=roots.backup,
    )


def validate_output_path(path: Path | str | None, roots: PathRoots, *, label: str = "output_path") -> Path | None:
    return validate_path_under_roots(path, roots.output, label=label)


def validate_final_output_path(path: Path | str | None, roots: PathRoots, *, label: str = "final_output_path") -> Path | None:
    return validate_path_under_roots(path, roots.media, label=label)


def validate_backup_path(path: Path | str | None, roots: PathRoots, *, label: str = "original_backup_path") -> Path | None:
    return validate_path_under_roots(path, roots.backup, label=label)


def validate_replacement_payload_paths(payload: Any, roots: PathRoots, *, label: str = "replacement_payload") -> Any:
    return _validate_payload_paths(payload, roots.replacement_payload, label=label)


def validate_path_under_roots(
    path: Path | str | None,
    roots: Iterable[Path],
    *,
    label: str,
) -> Path | None:
    if path is None:
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ApiValidationError(f"{label} must be an absolute path.")
    resolved = _resolve_for_authorization(candidate)
    resolved_roots = tuple(_resolve_for_authorization(root.expanduser()) for root in roots)
    if not resolved_roots:
        raise ApiValidationError(f"No configured roots are available to authorize {label}.")
    if not any(_is_relative_to(resolved, root) for root in resolved_roots):
        raise ApiValidationError(f"{label} is outside the configured media, scratch, or backup roots.")
    return resolved


def remap_worker_path_to_server_path(path: Path | str | None, mappings: list[dict] | None) -> Path | None:
    if path is None:
        return None
    raw_path = str(path)
    for mapping in normalise_path_mappings(mappings):
        suffix = _worker_path_suffix(raw_path, str(mapping["worker_path"]))
        if suffix is None:
            continue
        server_root = Path(mapping["server_path"])
        return _resolve_for_authorization(server_root.joinpath(*suffix))
    return Path(raw_path)


def remap_worker_payload_paths(payload: Any, mappings: list[dict] | None) -> Any:
    if isinstance(payload, dict):
        cleaned: dict[Any, Any] = {}
        for key, value in payload.items():
            if _is_path_key(key):
                cleaned[key] = _remap_payload_path_value(value, mappings)
            else:
                cleaned[key] = remap_worker_payload_paths(value, mappings)
        return cleaned
    if isinstance(payload, list):
        return [remap_worker_payload_paths(item, mappings) for item in payload]
    return payload


def _validate_payload_paths(payload: Any, roots: Iterable[Path], *, label: str) -> Any:
    if isinstance(payload, dict):
        cleaned: dict[Any, Any] = {}
        for key, value in payload.items():
            child_label = f"{label}.{key}"
            if _is_path_key(key):
                cleaned[key] = _validate_payload_path_value(value, roots, label=child_label)
            else:
                cleaned[key] = _validate_payload_paths(value, roots, label=child_label)
        return cleaned
    if isinstance(payload, list):
        return [
            _validate_payload_paths(item, roots, label=f"{label}[{index}]")
            for index, item in enumerate(payload)
        ]
    return payload


def _remap_payload_path_value(value: Any, mappings: list[dict] | None) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        mapped = remap_worker_path_to_server_path(value, mappings)
        return mapped.as_posix() if mapped is not None else None
    if isinstance(value, list):
        return [_remap_payload_path_value(item, mappings) for item in value]
    if isinstance(value, dict):
        return remap_worker_payload_paths(value, mappings)
    return value


def _validate_payload_path_value(value: Any, roots: Iterable[Path], *, label: str) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        path = validate_path_under_roots(value, roots, label=label)
        return path.as_posix() if path is not None else None
    if isinstance(value, list):
        return [
            _validate_payload_path_value(item, roots, label=f"{label}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return _validate_payload_paths(value, roots, label=label)
    return value


def _is_path_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.strip().lower()
    return lowered in _PATH_KEY_NAMES or lowered.endswith("_path")


def _resolve_for_authorization(path: Path) -> Path:
    return path.resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _deduplicate_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = _resolve_for_authorization(Path(path).expanduser())
        key = resolved.as_posix()
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return tuple(result)


def _worker_path_suffix(path_text: str, root_text: str) -> tuple[str, ...] | None:
    windows_style = _looks_like_windows_path(path_text) or _looks_like_windows_path(root_text)
    normal_path = _normalise_worker_path_text(path_text, windows_style=windows_style)
    normal_root = _normalise_worker_path_text(root_text, windows_style=windows_style)
    compare_path = normal_path.lower() if windows_style else normal_path
    compare_root = normal_root.lower() if windows_style else normal_root
    if compare_path == compare_root:
        return ()
    root_prefix = compare_root.rstrip("/")
    if not compare_path.startswith(f"{root_prefix}/"):
        return None
    suffix = normal_path[len(root_prefix):].lstrip("/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _normalise_worker_path_text(path_text: str, *, windows_style: bool) -> str:
    if windows_style:
        return posixpath.normpath(PureWindowsPath(path_text).as_posix())
    return posixpath.normpath(path_text.replace("\\", "/"))


def _looks_like_windows_path(path_text: str) -> bool:
    return bool(_WINDOWS_DRIVE_RE.match(path_text)) or "\\" in path_text
