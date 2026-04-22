#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the Encodr hardware-aware compose override.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Path to the Encodr project root.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(args.project_root).resolve()
    sys.path.insert(0, str(project_root / "packages" / "shared"))
    from encodr_shared.runtime_compose import write_runtime_compose_files

    write_runtime_compose_files(project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
