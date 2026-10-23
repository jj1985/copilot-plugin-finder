"""Paths, token resolution and run settings."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # copilot-plugin-finder/


def resolve_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "CPF_GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name].strip()
    gh = shutil.which("gh")
    if gh:
        try:
            out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    raise SystemExit("No GitHub token: set GITHUB_TOKEN or log in with `gh auth login`.")


@dataclass
class Settings:
    root: Path = ROOT
    db_path: Path = field(default_factory=lambda: ROOT / "data" / "index.sqlite")
    rules_dir: Path = field(default_factory=lambda: ROOT / "rules")
    export_dir: Path = field(default_factory=lambda: ROOT / "data" / "export")
    token: str | None = None
    # Budget caps per run (None = unlimited). Code search is 10/min, so 300 ≈ 30 min.
    max_code_search_requests: int | None = None
    verbose: bool = False

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def get_token(self) -> str:
        if not self.token:
            self.token = resolve_token()
        return self.token
