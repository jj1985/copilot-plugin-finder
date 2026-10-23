"""Load rules/markers.yaml into Family objects and apply the exact-path hit filter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Family:
    id: str
    group: str
    kind: str  # marketplace | plugin | pointer
    query: str
    path_regex: re.Pattern
    forks: bool = True
    slice_axes: list[str] = field(default_factory=lambda: ["size", "owner"])

    def accepts(self, path: str) -> bool:
        return bool(self.path_regex.match(path))


@dataclass
class Rules:
    version: int
    families: list[Family]
    max_hits_per_slice: int
    size_min: int
    size_max: int
    term_axis: list[str]
    groups: dict[str, dict]

    def select(self, groups: list[str] | None = None, ids: list[str] | None = None) -> list[Family]:
        out = []
        for f in self.families:
            if groups and f.group not in groups:
                continue
            if ids and f.id not in ids:
                continue
            out.append(f)
        return out

    def by_id(self, fid: str) -> Family:
        for f in self.families:
            if f.id == fid:
                return f
        raise KeyError(fid)


def load_rules(rules_dir: Path) -> Rules:
    data = yaml.safe_load((rules_dir / "markers.yaml").read_text(encoding="utf-8"))
    fams = []
    for raw in data["families"]:
        fams.append(
            Family(
                id=raw["id"],
                group=raw["group"],
                kind=raw["kind"],
                query=raw["query"].strip(),
                path_regex=re.compile(raw["path_regex"]),
                forks=bool(raw.get("forks", True)),
                slice_axes=list(raw.get("slice_axes") or ["size", "owner"]),
            )
        )
    size_axis = data.get("size_axis") or {}
    return Rules(
        version=int(data.get("version", 1)),
        families=fams,
        max_hits_per_slice=int(data.get("max_hits_per_slice", 950)),
        size_min=int(size_axis.get("min", 0)),
        size_max=int(size_axis.get("max", 400000)),
        term_axis=list(data.get("term_axis") or []),
        groups=dict(data.get("groups") or {}),
    )


def load_golden(rules_dir: Path) -> list[dict]:
    p = rules_dir / "golden.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list(data.get("repos") or [])
