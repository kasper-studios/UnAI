"""UnAI MCP Server implementation.
Loads all enabled workspaces from ~/.unai/workspaces/, discovers their @tool decorated methods,
and exposes them via Model Context Protocol (MCP) using stdio transport.
"""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

# Create FastMCP server instance
mcp = FastMCP("UnAI Universal Runtime")


def get_unai_home() -> Path:
    return Path.home() / ".unai"


def load_enabled_workspaces() -> None:
    workspaces_dir = get_unai_home() / "workspaces"
    if not workspaces_dir.exists():
        return

    for ws_path in workspaces_dir.iterdir():
        if not ws_path.is_dir():
            continue
        ws_id = ws_path.name
        
        # Check state.json
        state_file = ws_path / "state.json"
        enabled = False
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                enabled = data.get("enabled", False)
            except Exception:
                pass
        else:
            # Fallback to manifest default_enabled
            manifest_file = ws_path / "manifest.toml"
            if manifest_file.exists():
                try:
                    import toml
                    manifest = toml.loads(manifest_file.read_text())
                    enabled = manifest.get("default_enabled", False)
                except Exception:
                    pass

        if not enabled:
            continue

        # Load workspace.py
        ws_py = ws_path / "workspace.py"
        if not ws_py.exists():
            continue

        try:
            # Add workspace dir to sys.path temporarily
            sys.path.insert(0, str(ws_path))
            spec = importlib.util.spec_from_file_location(f"workspace_{ws_id}", str(ws_py))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[f"workspace_{ws_id}"] = mod
                spec.loader.exec_module(mod)

                # Find Workspace subclasses and instantiate them
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if isinstance(attr, type) and hasattr(attr, "_tools") and attr._tools:
                        instance = attr(runtime_id=ws_id)
                        for tool_name, tool_spec in instance.tools.items():
                            fn = tool_spec.bound or tool_spec.handler
                            if fn:
                                mcp.tool(
                                    name=tool_spec.name,
                                    description=tool_spec.description,
                                )(fn)
        except Exception as e:
            print(f"Error loading workspace {ws_id}: {e}", file=sys.stderr)


def main() -> None:
    load_enabled_workspaces()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
