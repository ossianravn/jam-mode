#!/usr/bin/env python3
"""Local preflight validator for the JAM Mode Codex plugin package.

This validates the runtime-facing manifest, marketplace, skill, and bundled MCP
layout used by the local Desktop/CLI installer. Public directory submission has
additional identity, URL, review, asset, and domain-verification requirements.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
MCP_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CATEGORIES = {
    "Productivity",
    "Creativity",
    "Developer Tools",
    "Business & Operations",
    "Data & Analytics",
    "Communication",
    "Education & Research",
    "Security",
    "Finance",
    "Healthcare",
    "Travel",
    "Entertainment",
    "Other",
}


class ValidationError(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"Missing required file: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ValidationError(f"File is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {path}: {exc}") from exc


def _require_text(container: dict[str, Any], key: str, label: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label}.{key} is required and must be non-empty text.")
    return value.strip()


def _resolve_component(plugin_root: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.startswith("./"):
        raise ValidationError(f"{label} must be a ./-prefixed path relative to the plugin root.")
    candidate = (plugin_root / raw).resolve()
    try:
        candidate.relative_to(plugin_root.resolve())
    except ValueError as exc:
        raise ValidationError(f"{label} escapes the plugin root: {raw}") from exc
    if not candidate.exists():
        raise ValidationError(f"{label} does not exist: {candidate}")
    return candidate


def _validate_manifest(plugin_root: Path) -> dict[str, Any]:
    path = plugin_root / ".codex-plugin" / "plugin.json"
    manifest = _load_json(path)
    if not isinstance(manifest, dict):
        raise ValidationError("plugin.json must contain a JSON object.")

    name = _require_text(manifest, "name", "plugin")
    if not NAME_RE.fullmatch(name):
        raise ValidationError("plugin.name must contain only letters, digits, '_' or '-' and start alphanumeric.")
    version = _require_text(manifest, "version", "plugin")
    if not SEMVER_RE.fullmatch(version):
        raise ValidationError(f"plugin.version is not strict semantic versioning: {version}")
    description = _require_text(manifest, "description", "plugin")
    if len(description) > 1024:
        raise ValidationError("plugin.description exceeds 1,024 characters.")

    author = manifest.get("author")
    if not isinstance(author, dict):
        raise ValidationError("plugin.author must be an object.")
    author_name = _require_text(author, "name", "plugin.author")
    if len(author_name) > 120:
        raise ValidationError("plugin.author.name exceeds 120 characters.")

    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise ValidationError("plugin.interface must be an object.")
    display_name = _require_text(interface, "displayName", "plugin.interface")
    short_description = _require_text(interface, "shortDescription", "plugin.interface")
    long_description = _require_text(interface, "longDescription", "plugin.interface")
    developer_name = _require_text(interface, "developerName", "plugin.interface")
    category = _require_text(interface, "category", "plugin.interface")
    capabilities = interface.get("capabilities")

    if len(display_name) > 80:
        raise ValidationError("interface.displayName exceeds 80 characters.")
    if "\n" in short_description or len(short_description) > 240:
        raise ValidationError("interface.shortDescription must be one line and at most 240 characters.")
    if len(long_description) > 4000:
        raise ValidationError("interface.longDescription exceeds 4,000 characters.")
    if len(developer_name) > 120:
        raise ValidationError("interface.developerName exceeds 120 characters.")
    if developer_name != author_name:
        raise ValidationError("interface.developerName must match author.name for predictable listing identity.")
    if category not in CATEGORIES:
        raise ValidationError(f"Unsupported interface.category: {category}")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValidationError("interface.capabilities must be a non-empty list of strings.")
    if len(capabilities) > 20 or any(
        not isinstance(item, str) or not item.strip() or len(item) > 120
        for item in capabilities
    ):
        raise ValidationError("interface.capabilities contains an invalid entry.")

    prompts = interface.get("defaultPrompt", [])
    if not isinstance(prompts, list) or len(prompts) > 3:
        raise ValidationError("interface.defaultPrompt must contain at most three strings.")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in prompts):
        raise ValidationError("Each interface.defaultPrompt entry must be non-empty and at most 128 characters.")

    skills_path = _resolve_component(plugin_root, manifest.get("skills"), "plugin.skills")
    if not skills_path.is_dir() or not any(skills_path.glob("*/SKILL.md")):
        raise ValidationError("plugin.skills must contain at least one skills/<name>/SKILL.md.")
    mcp_path = _resolve_component(plugin_root, manifest.get("mcpServers"), "plugin.mcpServers")
    if not mcp_path.is_file():
        raise ValidationError("plugin.mcpServers must resolve to a JSON file.")

    if "[TODO:" in path.read_text(encoding="utf-8"):
        raise ValidationError("plugin.json contains an unresolved [TODO: ...] placeholder.")
    return manifest


def _validate_mcp(plugin_root: Path, manifest: dict[str, Any]) -> None:
    mcp_path = _resolve_component(plugin_root, manifest["mcpServers"], "plugin.mcpServers")
    payload = _load_json(mcp_path)
    if not isinstance(payload, dict):
        raise ValidationError(".mcp.json must contain a JSON object.")
    if "mcp_servers" in payload:
        raise ValidationError("Use the plugin JSON key 'mcpServers', not config.toml's 'mcp_servers'.")
    servers = payload.get("mcpServers", payload)
    if not isinstance(servers, dict) or not servers:
        raise ValidationError(".mcp.json must contain a non-empty mcpServers object or top-level server map.")
    for name, config in servers.items():
        if not isinstance(name, str) or not MCP_NAME_RE.fullmatch(name):
            raise ValidationError(
                f"MCP server name {name!r} is not a callable namespace identifier; use letters, digits, and underscores."
            )
        if not isinstance(config, dict):
            raise ValidationError(f"MCP server {name!r} configuration must be an object.")
        command = config.get("command")
        args = config.get("args", [])
        if not isinstance(command, str) or not command.strip():
            raise ValidationError(f"MCP server {name!r} must define a command.")
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValidationError(f"MCP server {name!r} args must be a list of strings.")


def _validate_marketplace(plugin_root: Path, manifest: dict[str, Any]) -> None:
    marketplace_root = plugin_root.parents[1]
    marketplace_path = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    payload = _load_json(marketplace_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("plugins"), list):
        raise ValidationError("marketplace.json must contain a plugins array.")
    matches = [entry for entry in payload["plugins"] if isinstance(entry, dict) and entry.get("name") == manifest["name"]]
    if len(matches) != 1:
        raise ValidationError(f"marketplace.json must contain exactly one entry for {manifest['name']!r}.")
    entry = matches[0]
    source = entry.get("source")
    if not isinstance(source, dict) or source.get("source") != "local":
        raise ValidationError("The JAM development marketplace entry must use a local source.")
    raw_path = source.get("path")
    if not isinstance(raw_path, str):
        raise ValidationError("Marketplace source.path is required.")
    resolved = (marketplace_root / raw_path).resolve()
    if resolved != plugin_root.resolve():
        raise ValidationError(f"Marketplace source resolves to {resolved}, expected {plugin_root.resolve()}.")


def validate(plugin_root: Path) -> None:
    plugin_root = plugin_root.expanduser().resolve()
    if not plugin_root.is_dir():
        raise ValidationError(f"Plugin root is not a directory: {plugin_root}")
    manifest = _validate_manifest(plugin_root)
    _validate_mcp(plugin_root, manifest)
    _validate_marketplace(plugin_root, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the local JAM Mode Codex plugin package")
    parser.add_argument(
        "plugin_root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path containing .codex-plugin/plugin.json",
    )
    args = parser.parse_args(argv)
    try:
        validate(Path(args.plugin_root))
    except ValidationError as exc:
        print(f"JAM plugin validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"JAM plugin validation passed: {Path(args.plugin_root).expanduser().resolve()}")
    print("Scope: local Desktop/CLI package. Public directory submission checks are intentionally not included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
