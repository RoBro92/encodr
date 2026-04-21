from __future__ import annotations

import json
from pathlib import Path

from app.services.errors import ApiValidationError
from encodr_core.config import ConfigBundle


class SetupStateService:
    def __init__(self, *, config_bundle: ConfigBundle) -> None:
        self.config_bundle = config_bundle
        self.state_path = self.config_bundle.app.data_dir / "setup-state.json"

    def get_state(self) -> dict[str, str | None]:
        if not self.state_path.exists():
            return {"movies_root": None, "tv_root": None}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"movies_root": None, "tv_root": None}
        return {
            "movies_root": self._clean_optional_path(payload.get("movies_root")),
            "tv_root": self._clean_optional_path(payload.get("tv_root")),
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
        payload = {
            "movies_root": resolved_movies.as_posix() if resolved_movies is not None else None,
            "tv_root": resolved_tv.as_posix() if resolved_tv is not None else None,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload

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
