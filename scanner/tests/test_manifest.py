import json

from cpf.manifest import (
    _strip_jsonc,
    compute_facets,
    marketplaces_from_settings,
    normalize_source,
    parse_marketplace,
    parse_plugin,
    parse_settings,
    readme_excerpt,
)
from cpf.markers import Family
import re

AP = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def mk(**kw):
    base = {"name": "my-market", "owner": {"name": "x"}, "plugins": [{"name": "a", "source": "./plugins/a"}]}
    base.update(kw)
    return json.dumps(base)


def test_marketplace_ok_and_warnings():
    r = parse_marketplace(".github/plugin/marketplace.json", mk())
    assert r.ok and r.format == "legacy" and not r.warnings
    r = parse_marketplace(".claude-plugin/marketplace.json", mk(owner={}))
    assert r.ok and r.format == "claude" and "owner.name missing" in r.warnings
    r = parse_marketplace("marketplace.json", json.dumps({"name": "x", "plugins": [{"name": "p", "source": {"source": "github", "repo": "o/r", "sha": "abc"}}]}))
    assert r.ok and any("sha" in w for w in r.warnings)


def test_marketplace_invalid():
    assert not parse_marketplace("marketplace.json", "{not json").ok
    assert parse_marketplace("marketplace.json", json.dumps({"name": "x"})).error == "missing plugins[]"
    assert parse_marketplace("marketplace.json", json.dumps([1, 2])).error == "not an object"


def test_agent_plugins_manifest_requires_schema_and_name():
    r = parse_plugin("plugin.json", json.dumps({"$schema": AP, "name": "ok.name", "extra": 1}))
    assert r.ok and r.format == "agent-plugins-1.0"
    assert any("unknown top-level" in w for w in r.warnings)
    r = parse_plugin("plugin.json", json.dumps({"$schema": AP}))
    assert not r.ok and r.error == "missing name"
    r = parse_plugin("plugin.json", json.dumps({"$schema": "https://agent-plugins.org/schemas/9.0.0/plugin.schema.json", "name": "x"}))
    assert not r.ok and "unsupported" in r.error
    r = parse_plugin("plugin.json", json.dumps({"$schema": AP, "name": "Bad--Name"}))
    assert r.ok and any("name constraints" in w for w in r.warnings)


def test_root_legacy_plugin_json_needs_plugin_structure():
    # Obsidian/Jenkins-style root plugin.json must be rejected
    r = parse_plugin("plugin.json", json.dumps({"name": "obsidian-thing", "id": "x", "minAppVersion": "1.0"}), root_entries={"src", "package.json"})
    assert not r.ok and "without plugin structure" in r.error
    # same file with a skills/ sibling is accepted
    r = parse_plugin("plugin.json", json.dumps({"name": "my-plugin"}), root_entries={"skills"})
    assert r.ok and r.format == "legacy"
    # component path fields count too
    r = parse_plugin("plugin.json", json.dumps({"name": "my-plugin", "hooks": "hooks.json"}), root_entries=set())
    assert r.ok
    # non-root legacy manifests never need the sibling check
    r = parse_plugin(".github/plugin/plugin.json", json.dumps({"name": "my-plugin"}))
    assert r.ok


def test_normalize_source_forms():
    s = normalize_source("./plugins/a", None)
    assert s["kind"] == "local" and s["path"] == "plugins/a"
    s = normalize_source("a", "./plugins")
    assert s["path"] == "plugins/a"
    s = normalize_source({"source": "github", "repo": "https://github.com/Owner/Repo.git", "sha": "a" * 40, "path": "p"}, None)
    assert s["kind"] == "github" and s["repo"] == "Owner/Repo" and s["pinned"] == 1 and s["path"] == "p"
    s = normalize_source({"source": "url", "url": "https://gitlab.com/o/r.git"}, None)
    assert s["kind"] == "url" and s["host"] == "gitlab.com"
    s = normalize_source({"source": "npm", "package": "@x/y"}, None)
    assert s["kind"] == "npm" and s["host"] == "npmjs.com" and s["path"] == "@x/y"
    assert normalize_source(42, None)["kind"] == "invalid"


def test_facets_dual_format_and_shadowing():
    manifests = {
        ".github/plugin/marketplace.json": parse_marketplace(".github/plugin/marketplace.json", mk()),
        ".claude-plugin/marketplace.json": parse_marketplace(".claude-plugin/marketplace.json", mk()),
    }
    f = compute_facets({".github", ".claude-plugin", "plugins"}, manifests)
    assert f.kind == "marketplace" and f.native_level == "copilot-authored" and f.evidence == "verified-root"
    assert f.dual_format == 1 and f.copilot_specific == 1
    assert f.effective_marketplace_path == ".github/plugin/marketplace.json"
    assert not any("shadowed" in w for w in f.warnings)  # effective one is valid: not a problem

    # an invalid root marketplace.json shadows the valid .github one
    manifests["marketplace.json"] = parse_marketplace("marketplace.json", "{broken")
    f = compute_facets({"marketplace.json", ".github", ".claude-plugin"}, manifests)
    assert f.effective_marketplace_path == "marketplace.json"
    assert any("shadowed" in w for w in f.warnings)
    assert f.kind is None  # CLI would hit the broken one first


def test_facets_claude_only_and_executes_code():
    manifests = {".claude-plugin/plugin.json": parse_plugin(".claude-plugin/plugin.json", json.dumps({"name": "p", "hooks": "hooks.json", "mcpServers": ".mcp.json"}))}
    f = compute_facets({".claude-plugin", "hooks.json", ".mcp.json"}, manifests)
    assert f.kind == "plugin" and f.native_level == "copilot-installable-claude-format"
    assert set(f.executes_code) >= {"hooks", "mcp"}
    assert f.format == "claude"


def test_facets_agent_plugins_with_copilot_dir():
    manifests = {"plugin.json": parse_plugin("plugin.json", json.dumps({"$schema": AP, "name": "x"}))}
    f = compute_facets({"plugin.json", "skills", "com.github.copilot"}, manifests)
    assert f.native_level == "copilot-authored" and f.format == "agent-plugins-1.0" and f.copilot_specific == 1
    assert "copilot-components" in f.executes_code


def test_settings_and_jsonc():
    txt = '{ // comment\n "extraKnownMarketplaces": { "m": { "source": { "source": "github", "repo": "o/r" } }, },\n "enabledPlugins": {"a@m": true, "b@m": false} }'
    r = parse_settings(".github/copilot/settings.json", txt)
    assert r.ok
    ms = marketplaces_from_settings(r.data)
    assert ms[0]["repo"] == "o/r" and ms[0]["name"] == "m"
    assert _strip_jsonc('{"a": "http://x//y", /* c */ "b": 1,}') == '{"a": "http://x//y",  "b": 1}'
    vs = parse_settings(".vscode/settings.json", json.dumps({"chat.plugins.marketplaces": ["anthropics/claude-code#main"]}))
    m = marketplaces_from_settings(vs.data)[0]
    assert (m["repo"], m["ref"], m["url"]) == ("anthropics/claude-code", "main", None)
    # local-file marketplaces (common in dotfiles) still count as adoption
    from cpf.manifest import marketplace_ref
    loc = parse_settings(".claude/settings.json", json.dumps({"extraKnownMarketplaces": {"g": {"source": {"source": "file", "path": "/x/marketplace.json"}}}}))
    assert marketplace_ref(marketplaces_from_settings(loc.data)[0]) == "file:/x/marketplace.json"


def test_readme_excerpt_strips_markup():
    t = readme_excerpt("# Title\n\n![img](x.png) Some **bold** [link](http://x) text‮ here", limit=50)
    assert t.startswith("Title Some bold link text here")
    assert "‮" not in t


def test_family_exact_path_filter():
    fam = Family(id="M-GH", group="g", kind="marketplace", query="q", path_regex=re.compile(r"^\.github/plugin/marketplace\.json$"))
    assert fam.accepts(".github/plugin/marketplace.json")
    assert not fam.accepts("soar-toolkit/.github/plugin/marketplace.json")
    assert not fam.accepts(".github/plugin/umbraco-marketplace.json")
    assert not fam.accepts(".github/plugins/marketplace.json")
