"""Manifest parsing, validation, source normalisation and facet computation (PLAN.md §2, §4).

Pure functions: no network, no database. Everything here is unit-testable with fixtures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# Copilot CLI lookup orders (docs: cli-plugin-reference, "File locations")
MARKETPLACE_ORDER = [
    "marketplace.json",
    ".plugin/marketplace.json",
    ".github/plugin/marketplace.json",
    ".claude-plugin/marketplace.json",
]
PLUGIN_ORDER_LEGACY = [
    ".plugin/plugin.json",
    "plugin.json",
    ".github/plugin/plugin.json",
    ".claude-plugin/plugin.json",
]
ALL_MANIFEST_PATHS = MARKETPLACE_ORDER + PLUGIN_ORDER_LEGACY
SETTINGS_PATHS = [".github/copilot/settings.json", ".claude/settings.json", ".vscode/settings.json"]

AP_SCHEMAS = {
    "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json": "agent-plugins-1.0",
    "https://agent-plugins.org/schemas/1.1.0/plugin.schema.json": "agent-plugins-1.1",
}
AP_ALLOWED_FIELDS = {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords", "extensions"}
LEGACY_COMPONENT_FIELDS = {"agents", "skills", "commands", "hooks", "extensions", "mcpServers", "lspServers"}
LEGACY_META_FIELDS = {"name", "description", "version", "author", "homepage", "repository", "license", "keywords", "category", "tags"}
ENTRY_COMPONENT_FIELDS = {"commands", "agents", "skills", "hooks", "mcpServers", "lspServers"}

AP_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
LEGACY_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
GITHUB_REPO_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")

# Root-level names that indicate plugin structure for a root plugin.json without an Agent Plugins schema
PLUGIN_SIBLINGS = {"skills", "agents", "commands", "hooks", "hooks.json", ".mcp.json", "mcp.json", "lsp.json",
                   "com.github.copilot", "SKILL.md", "extensions"}


@dataclass
class ManifestResult:
    path: str
    kind: str                      # marketplace | plugin | settings
    ok: bool = False
    format: str | None = None      # agent-plugins-1.0 | agent-plugins-1.1 | legacy | claude
    data: dict | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------- JSON ----------------

def parse_json(text: str | None) -> tuple[Any, str | None]:
    if text is None:
        return None, "no text"
    if len(text) > 2_000_000:
        return None, "too large"
    try:
        return json.loads(text), None
    except (ValueError, RecursionError) as exc:
        return None, f"invalid JSON: {str(exc)[:120]}"


# ---------------- marketplace ----------------

def parse_marketplace(path: str, text: str | None) -> ManifestResult:
    r = ManifestResult(path=path, kind="marketplace")
    obj, err = parse_json(text)
    if err or not isinstance(obj, dict):
        r.error = err or "not an object"
        return r
    r.data = obj
    name = obj.get("name")
    owner = obj.get("owner")
    plugins = obj.get("plugins")
    if not isinstance(name, str) or not name:
        r.error = "missing name"
        return r
    if not isinstance(plugins, list):
        r.error = "missing plugins[]"
        return r
    if not isinstance(owner, dict) or not owner.get("name"):
        r.warnings.append("owner.name missing")
    if len(name) > 64:
        r.warnings.append("name longer than 64")
    if not (LEGACY_NAME_RE.match(name) or AP_NAME_RE.match(name)):
        r.warnings.append("name not kebab-case")
    bad = 0
    for i, p in enumerate(plugins):
        if not isinstance(p, dict) or not p.get("name") or "source" not in p:
            bad += 1
            continue
        d = p.get("description")
        if isinstance(d, str) and len(d) > 1024:
            r.warnings.append(f"plugins[{i}].description longer than 1024")
        src = p.get("source")
        if isinstance(src, dict):
            sha = src.get("sha")
            if sha and not SHA40_RE.match(str(sha)):
                r.warnings.append(f"plugins[{i}].source.sha is not 40 hex chars")
    if bad:
        r.warnings.append(f"{bad} plugin entries lack name or source")
    r.ok = bad < len(plugins) or len(plugins) == 0
    r.format = "claude" if path.startswith(".claude-plugin/") else "legacy"
    return r


# ---------------- plugin ----------------

def parse_plugin(path: str, text: str | None, root_entries: set[str] | None = None) -> ManifestResult:
    r = ManifestResult(path=path, kind="plugin")
    obj, err = parse_json(text)
    if err or not isinstance(obj, dict):
        r.error = err or "not an object"
        return r
    r.data = obj
    schema = obj.get("$schema")
    name = obj.get("name")
    if isinstance(schema, str) and "agent-plugins.org" in schema:
        fmt = AP_SCHEMAS.get(schema)
        if not fmt:
            r.error = f"unsupported Agent Plugins $schema: {schema[:80]}"
            return r
        r.format = fmt
        if path != "plugin.json":
            r.warnings.append("Agent Plugins manifest outside plugin root (CLI requires root plugin.json)")
        if not isinstance(name, str) or not name:
            r.error = "missing name"
            return r
        if not AP_NAME_RE.match(name) or "--" in name or ".." in name:
            r.warnings.append("name violates Agent Plugins name constraints")
        unknown = sorted(set(obj) - AP_ALLOWED_FIELDS)
        if unknown:
            r.warnings.append(f"unknown top-level fields ignored: {', '.join(unknown[:6])}")
        ext = obj.get("extensions")
        if ext is not None and not isinstance(ext, dict):
            r.warnings.append("extensions is not an object")
        r.ok = True
        return r

    # legacy
    r.format = "claude" if path.startswith(".claude-plugin/") else "legacy"
    if not isinstance(name, str) or not name:
        r.error = "missing name"
        return r
    if len(name) > 64 or not LEGACY_NAME_RE.match(name):
        r.warnings.append("name not kebab-case (legacy rule)")
    d = obj.get("description")
    if isinstance(d, str) and len(d) > 1024:
        r.warnings.append("description longer than 1024")
    author = obj.get("author")
    if isinstance(author, dict) and not author.get("name"):
        r.warnings.append("author.name missing")
    has_component_fields = bool(LEGACY_COMPONENT_FIELDS & set(obj))
    if path == "plugin.json":
        # A root plugin.json without a schema is shared with other ecosystems: require plugin structure.
        siblings = set(root_entries or ())
        if not (has_component_fields or (siblings & PLUGIN_SIBLINGS)):
            r.error = "root plugin.json without plugin structure (no skills/agents/hooks/mcp siblings or component fields)"
            return r
    r.ok = True
    return r


# ---------------- settings (adopters) ----------------

def parse_settings(path: str, text: str | None) -> ManifestResult:
    r = ManifestResult(path=path, kind="settings")
    obj, err = parse_json(_strip_jsonc(text) if text else text)
    if err or not isinstance(obj, dict):
        r.error = err or "not an object"
        return r
    r.data = obj
    r.ok = True
    return r


def _strip_jsonc(text: str) -> str:
    # .vscode/settings.json is JSONC; remove // and /* */ comments outside strings and trailing commas.
    out, i, n, in_str, esc = [], 0, len(text), False, False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    s = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", s)


def marketplaces_from_settings(obj: dict) -> list[dict]:
    """Return [{name, repo|url, ref}] from extraKnownMarketplaces and chat.plugins.marketplaces."""
    out: list[dict] = []
    ekm = obj.get("extraKnownMarketplaces")
    if isinstance(ekm, dict):
        for name, spec in ekm.items():
            src = (spec or {}).get("source") if isinstance(spec, dict) else None
            if isinstance(src, dict):
                norm = normalize_source(src, None)
                out.append({"name": name, "repo": norm.get("repo"), "url": norm.get("url"), "ref": norm.get("ref"),
                            "kind": norm.get("kind"), "path": norm.get("path")})
            elif isinstance(spec, str):
                out.append({"name": name, "kind": "github", "path": None, **_repo_or_url(spec)})
    vsc = obj.get("chat.plugins.marketplaces")
    if isinstance(vsc, list):
        for s in vsc:
            if isinstance(s, str):
                out.append({"name": None, "kind": "github", "path": None, **_repo_or_url(s)})
    return out


def marketplace_ref(m: dict) -> str | None:
    """Stable string for an adopter's marketplace: 'owner/repo', a URL, or 'kind:path' for local/other sources."""
    if m.get("repo"):
        return m["repo"]
    if m.get("url"):
        return m["url"]
    if m.get("kind") and m.get("path"):
        return f"{m['kind']}:{m['path']}"
    if m.get("kind") and m.get("kind") not in ("unknown", "invalid"):
        return f"{m['kind']}:{m.get('name') or ''}"
    return None


def enabled_plugins_from_settings(obj: dict) -> list[str]:
    ep = obj.get("enabledPlugins")
    if isinstance(ep, dict):
        return [k for k, v in ep.items() if v]
    if isinstance(ep, list):
        return [str(k) for k in ep]
    return []


# ---------------- sources ----------------

def _repo_or_url(s: str) -> dict:
    s = s.strip()
    ref = None
    if "#" in s and not s.startswith("http"):
        s, ref = s.split("#", 1)
    m = GITHUB_REPO_RE.match(s)
    if m:
        return {"repo": f"{m.group(1)}/{m.group(2)}", "url": None, "ref": ref}
    return {"repo": None, "url": s, "ref": ref}


def normalize_source(src: Any, plugin_root: str | None) -> dict:
    """Normalise a marketplace entry `source` into kind/host/repo/path/ref/sha/pinned/url."""
    out = {"kind": None, "host": None, "repo": None, "path": None, "ref": None, "sha": None, "pinned": 0, "url": None}
    if isinstance(src, str):
        s = src.strip()
        if s.startswith(("http://", "https://", "git@")):
            out.update(_url_source(s))
            return out
        p = s.removeprefix("./")
        if plugin_root:
            p = f"{plugin_root.strip('/').removeprefix('./')}/{p}".strip("/")
        out.update(kind="local", path=p.strip("/") or ".")
        return out
    if isinstance(src, dict):
        kind = str(src.get("source") or src.get("type") or "unknown")
        out["kind"] = kind
        out["path"] = src.get("path")
        out["ref"] = src.get("ref") or src.get("branch") or src.get("tag")
        sha = src.get("sha") or src.get("commit")
        out["sha"] = sha
        out["pinned"] = int(bool(sha and SHA40_RE.match(str(sha))))
        if kind == "github" and src.get("repo"):
            m = GITHUB_REPO_RE.match(str(src["repo"]).strip())
            out["host"] = "github.com"
            out["repo"] = f"{m.group(1)}/{m.group(2)}" if m else str(src["repo"])
        elif src.get("url"):
            out.update({k: v for k, v in _url_source(str(src["url"])).items() if k != "kind"})
            if kind == "unknown":
                out["kind"] = "url"
        elif kind in ("npm", "pip", "pypi"):
            out["host"] = "npmjs.com" if kind == "npm" else "pypi.org"
            out["path"] = src.get("package") or src.get("name")
        return out
    out["kind"] = "invalid"
    return out


def _url_source(url: str) -> dict:
    m = GITHUB_REPO_RE.match(url)
    if m:
        return {"kind": "github", "host": "github.com", "repo": f"{m.group(1)}/{m.group(2)}", "url": url}
    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None
    return {"kind": "url", "host": host, "url": url}


# ---------------- effective manifest and facets ----------------

def effective_manifest(results: dict[str, ManifestResult], order: list[str], prefer_root_ap: bool = False) -> tuple[ManifestResult | None, list[str]]:
    """First existing manifest in CLI order; valid manifests behind an invalid first one are 'shadowed'."""
    seq = list(order)
    if prefer_root_ap:
        root = results.get("plugin.json")
        if root and root.format and root.format.startswith("agent-plugins") and root.ok:
            seq = ["plugin.json"] + [p for p in order if p != "plugin.json"]
    present = [results[p] for p in seq if p in results]
    if not present:
        return None, []
    eff = present[0]
    shadowed = [m.path for m in present[1:] if m.ok]
    if eff.ok:
        return eff, shadowed
    # effective one is invalid: still report it as effective (that is what the CLI would hit)
    return eff, shadowed


@dataclass
class Facets:
    kind: str | None = None
    native_level: str = "declared-only"
    evidence: str = "declared-only"
    format: str | None = None
    dual_format: int = 0
    copilot_specific: int = 0
    executes_code: list[str] = field(default_factory=list)
    effective_marketplace_path: str | None = None
    effective_plugin_path: str | None = None
    shadowed: list[str] = field(default_factory=list)
    schema_valid: int | None = None
    warnings: list[str] = field(default_factory=list)
    marketplace: dict | None = None
    plugin: dict | None = None


def compute_facets(root_entries: set[str], manifests: dict[str, ManifestResult], is_root: bool = True) -> Facets:
    f = Facets()
    fixed = {p: m for p, m in manifests.items() if p in ALL_MANIFEST_PATHS}
    nested = {p: m for p, m in manifests.items() if p not in ALL_MANIFEST_PATHS and m.kind == "plugin"}
    mk, mk_shadow = effective_manifest(fixed, MARKETPLACE_ORDER)
    pl, pl_shadow = effective_manifest(fixed, PLUGIN_ORDER_LEGACY, prefer_root_ap=True)
    if pl is None and nested:
        # Referenced as owner/repo:path (or inside plugins/): the plugin lives in a subdirectory.
        ok_nested = [m for m in nested.values() if m.ok] or list(nested.values())
        pl = sorted(ok_nested, key=lambda m: m.path)[0]
        if pl.ok:
            is_root = False
    f.shadowed = mk_shadow + pl_shadow
    mk_ok = bool(mk and mk.ok)
    pl_ok = bool(pl and pl.ok)
    if mk_ok and pl_ok:
        f.kind = "both"
    elif mk_ok:
        f.kind = "marketplace"
    elif pl_ok:
        f.kind = "plugin"
    f.effective_marketplace_path = mk.path if mk else None
    f.effective_plugin_path = pl.path if pl else None
    for m in (mk, pl):
        if m:
            f.warnings.extend(f"{m.path}: {w}" for w in m.warnings)
            if m.error:
                f.warnings.append(f"{m.path}: {m.error}")
    # Shadowing only matters when the manifest the CLI reaches first is invalid.
    if mk and not mk.ok and mk_shadow:
        f.warnings.append("effective marketplace manifest invalid; valid manifest shadowed: " + ", ".join(mk_shadow))
    if pl and not pl.ok and pl_shadow:
        f.warnings.append("effective plugin manifest invalid; valid manifest shadowed: " + ", ".join(pl_shadow))

    ok_paths = {p for p, m in manifests.items() if m.ok and m.kind in ("marketplace", "plugin")}
    copilot_paths = {p for p in ok_paths if p.startswith((".github/plugin/", ".plugin/")) or p in ("marketplace.json", "plugin.json")
                     or (p not in ALL_MANIFEST_PATHS and "/.claude-plugin/" not in p)}
    claude_paths = {p for p in ok_paths if p.startswith(".claude-plugin/") or "/.claude-plugin/" in p}
    f.dual_format = int(bool(copilot_paths) and bool(claude_paths))

    legacy_fields: set[str] = set()
    for m in manifests.values():
        if m.kind == "plugin" and m.ok and m.data and not (m.format or "").startswith("agent-plugins"):
            legacy_fields |= LEGACY_COMPONENT_FIELDS & set(m.data)
    entry_fields: set[str] = set()
    if mk_ok and mk.data:
        for p in mk.data.get("plugins") or []:
            if isinstance(p, dict):
                entry_fields |= ENTRY_COMPONENT_FIELDS & set(p)

    # Hooks and LSP servers exist in Claude plugins too; only Copilot SDK `extensions`, the
    # `com.github.copilot/` directory and Copilot manifest paths prove Copilot authorship.
    copilot_signal = bool(copilot_paths) or "com.github.copilot" in root_entries or "extensions" in legacy_fields
    f.copilot_specific = int("com.github.copilot" in root_entries or "extensions" in legacy_fields
                             or bool(copilot_paths & {".github/plugin/marketplace.json", ".github/plugin/plugin.json"}))
    if mk_ok or pl_ok:
        f.native_level = "copilot-authored" if copilot_signal else "copilot-installable-claude-format"
        f.evidence = "verified-root" if is_root else "verified-nested"
        f.schema_valid = int(not any(m.error for m in (mk, pl) if m))
    else:
        f.native_level = "declared-only"
        f.evidence = "declared-only"
        f.schema_valid = 0 if (mk or pl) else None

    if pl and pl.ok:
        f.format = pl.format
    elif mk and mk.ok:
        f.format = mk.format

    ex: set[str] = set()
    if {"hooks.json", "hooks"} & root_entries or "hooks" in legacy_fields or "hooks" in entry_fields:
        ex.add("hooks")
    if {"mcp.json", ".mcp.json"} & root_entries or "mcpServers" in legacy_fields or "mcpServers" in entry_fields:
        ex.add("mcp")
    if "lsp.json" in root_entries or "lspServers" in legacy_fields or "lspServers" in entry_fields:
        ex.add("lsp")
    if "extensions" in root_entries or "extensions" in legacy_fields:
        ex.add("extensions")
    if "com.github.copilot" in root_entries:
        ex.add("copilot-components")
    if "scripts" in root_entries:
        ex.add("scripts")
    f.executes_code = sorted(ex)

    if mk_ok and mk.data:
        md = mk.data.get("metadata") if isinstance(mk.data.get("metadata"), dict) else {}
        owner = mk.data.get("owner") if isinstance(mk.data.get("owner"), dict) else {}
        f.marketplace = {
            "name": mk.data.get("name"),
            "owner_name": owner.get("name"),
            "description": md.get("description"),
            "version": md.get("version"),
            "plugin_root": md.get("pluginRoot"),
            "plugins": plugin_entries(mk.data),
        }
    if pl_ok and pl.data:
        f.plugin = {
            "name": pl.data.get("name"),
            "version": pl.data.get("version"),
            "description": pl.data.get("description"),
            "format": pl.format,
            "keywords": pl.data.get("keywords") if isinstance(pl.data.get("keywords"), list) else None,
            "category": pl.data.get("category"),
            "tags": pl.data.get("tags") if isinstance(pl.data.get("tags"), list) else None,
            "component_fields": sorted(LEGACY_COMPONENT_FIELDS & set(pl.data)),
        }
    return f


def plugin_entries(marketplace: dict) -> list[dict]:
    md = marketplace.get("metadata") if isinstance(marketplace.get("metadata"), dict) else {}
    plugin_root = md.get("pluginRoot")
    out = []
    for p in marketplace.get("plugins") or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        src = normalize_source(p.get("source"), plugin_root)
        strict = p.get("strict")
        out.append({
            "name": str(p.get("name")),
            "version": p.get("version"),
            "description": p.get("description") if isinstance(p.get("description"), str) else None,
            "source": src,
            "keywords": p.get("keywords") if isinstance(p.get("keywords"), list) else None,
            "category": p.get("category"),
            "tags": p.get("tags") if isinstance(p.get("tags"), list) else None,
            "strict": None if strict is None else int(bool(strict)),
            "executes_code": sorted({"hooks"} if "hooks" in p else set()
                                    | ({"mcp"} if "mcpServers" in p else set())
                                    | ({"lsp"} if "lspServers" in p else set())),
        })
    return out


def readme_excerpt(text: str | None, limit: int = 300) -> str | None:
    if not text:
        return None
    t = re.sub(r"<[^>]+>", " ", text)                       # html tags
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)              # images
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)           # links -> text
    t = re.sub(r"[#>*_`|~-]{1,}", " ", t)                    # markdown punctuation
    t = re.sub(r"[​-‏‪-‮⁦-⁩]", "", t)  # bidi / zero-width
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit] if t else None
