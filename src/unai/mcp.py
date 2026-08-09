"""UnAI MCP Server implementation.
Loads all enabled workspaces from ~/.unai/workspaces/, discovers their @tool decorated methods,
and exposes them via Model Context Protocol (MCP) using stdio transport.

Internal (built-in) workspaces from internalws/ are loaded first.
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


def _find_runtime_dir() -> Path:
    """Locate the runtime source directory (contains src/, internalws/, etc.).

    Priority:
    1. ~/.unai/src/main (production install)
    2. Relative to this file: ../../ (dev — src/unai/mcp.py → main/)
    """
    prod = get_unai_home() / "src" / "main"
    if prod.exists() and (prod / "pyproject.toml").exists():
        return prod

    # Dev fallback: this file is at <root>/src/unai/mcp.py → root = ../..
    dev = Path(__file__).resolve().parent.parent.parent
    if (dev / "pyproject.toml").exists():
        return dev

    return prod  # will fail gracefully later


ACTIVE_WORKSPACES: List[Any] = []


def _register_workspace_tools(ws_id: str, ws_path: Path) -> None:
    """Load workspace.py from ws_path, find Workspace subclasses, register their @tool methods."""
    ws_py = ws_path / "workspace.py"
    if not ws_py.exists():
        return

    try:
        sys.path.insert(0, str(ws_path))
        spec = importlib.util.spec_from_file_location(f"workspace_{ws_id}", str(ws_py))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"workspace_{ws_id}"] = mod
            spec.loader.exec_module(mod)

            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and hasattr(attr, "_tools") and attr._tools:
                    instance = attr(runtime_id=ws_id)
                    ACTIVE_WORKSPACES.append(instance)
                    for tool_name, tool_spec in instance.tools.items():
                        fn = tool_spec.bound or tool_spec.handler
                        if fn:
                            mcp.tool(
                                name=tool_spec.name,
                                description=tool_spec.description,
                            )(fn)
    except Exception as e:
        print(f"Error loading workspace {ws_id}: {e}", file=sys.stderr)


def _parse_toml(manifest_file: Path) -> dict:
    text = manifest_file.read_text()
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        import toml
        return toml.loads(text)


def load_internal_workspaces() -> None:
    """Load built-in workspaces from <runtime_dir>/internalws/."""
    runtime_dir = _find_runtime_dir()
    internalws_dir = runtime_dir / "internalws"
    if not internalws_dir.exists():
        return

    for ws_path in internalws_dir.iterdir():
        if not ws_path.is_dir():
            continue
        ws_id = ws_path.name

        # Check manifest.toml for default_enabled
        manifest_file = ws_path / "manifest.toml"
        if not manifest_file.exists():
            continue

        enabled = False
        try:
            manifest = _parse_toml(manifest_file)
            enabled = manifest.get("default_enabled", False)
        except Exception:
            pass

        if not enabled:
            continue

        _register_workspace_tools(ws_id, ws_path)


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
                    manifest = _parse_toml(manifest_file)
                    enabled = manifest.get("default_enabled", False)
                except Exception:
                    pass

        if not enabled:
            continue

        _register_workspace_tools(ws_id, ws_path)


async def async_main() -> None:
    load_internal_workspaces()
    load_enabled_workspaces()
    for ws in ACTIVE_WORKSPACES:
        try:
            await ws.start()
        except Exception as e:
            print(f"Error starting workspace {getattr(ws, 'runtime_id', 'unknown')}: {e}", file=sys.stderr)
    await mcp.run_stdio_async()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
