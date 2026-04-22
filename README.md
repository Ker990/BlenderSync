# BlenderSync

Rhino to Blender export pipeline for architectural rendering.

## Components

- `rhino/` — Rhino export command (IronPython, runs inside Rhino)
- `blender/rhino_sync/` — Blender addon (import, sync, materials)
- `mcp/` — Blender MCP server for Claude Code (Phase 2)

## Quick Start

1. In Rhino: `RunPythonScript D:/BlenderSync/rhino/blender_sync.py`
2. In Blender: Install `blender/rhino_sync/` as addon
3. In Blender sidebar: Rhino Sync tab → set project folder → Sync
