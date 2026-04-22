# CLAUDE.md — BlenderSync

## What this project is

A standalone Rhino-to-Blender export pipeline for architectural rendering. Exports Rhino NURBS geometry as OBJ meshes with a JSON manifest, imports into Blender with layer-to-collection mapping, material auto-assignment, and GUID-based re-sync.

**Not part of rhino_bim.** Works with any Rhino file.

**Repo:** `D:/BlenderSync/` — GitHub: Ker990/BlenderSync

## Architecture

```
Rhino (IronPython)          Exchange Package              Blender (bpy addon)
  blender_sync.py    →    manifest.json + OBJ files    →    rhino_sync addon
  manifest.py                                                sync_engine.py
  mesh_utils.py                                              material_mapper.py
```

### Rhino side (`rhino/`)
- `blender_sync.py` — entry point, run via `RunPythonScript`
- `manifest.py` — walks doc objects + block definitions, builds manifest.json
- `mesh_utils.py` — `Mesh.CreateFromBrep()` + custom OBJ writer
- Uses RhinoCommon directly (not rhinoscriptsyntax) for speed
- `importlib.reload()` on every run so edits take effect without restarting Rhino
- `doc.Path` returns full file path in Rhino 8, use `os.path.dirname()` for directory
- String GUIDs must be converted to `System.Guid()` for `FindId()` lookups

### Blender side (`blender/rhino_sync/`)
- Standard Blender addon with `bl_info`, installed via zip
- N-panel in 3D Viewport sidebar ("Rhino Sync" tab)
- Direct OBJ parser (`_parse_obj_file`) — does NOT use `bpy.ops.wm.obj_import` (too slow)
- Builds meshes via `mesh.from_pydata(verts, [], faces)`
- GUID matching via `obj["rhino_guid"]` custom property

### Exchange format
- `{filename}_blender/manifest.json` — layer tree, object GUIDs, block definitions + instances
- `{filename}_blender/meshes/{guid}.obj` — one OBJ per regular object
- `{filename}_blender/blocks/{def_name}/piece_{i}.obj` — one OBJ per block sub-object

## Key behaviors

### Meshing
- `SimplePlanes = True` — critical for architecture, keeps flat surfaces minimal
- Preview: coarse tolerance (3mm), Final: smooth tolerance (0.3mm)
- OBJs are cached between exports — only new objects get meshed
- Set `sc.sticky["blendersync_clean"] = True` to force full re-export

### Block instances
- Each block definition exports sub-pieces as separate OBJs with internal layer info
- Blender creates real objects (not collection instances) parented to an empty
- Mesh data is shared across instances, materials are per-object
- Each piece is selectable and Tab-editable independently

### Re-sync (GUID matching)
- GUID match found → swap mesh data, keep materials/modifiers
- New GUID → add to collection, assign default material
- Old GUID missing → hide in `_Removed` collection (never auto-delete)
- Cameras, lights, HDRIs, render settings are never touched

### Material mapping
- `material_map.json` — case-insensitive substring matching on layer names
- Presets: Concrete, Glass, Wood, Metal, Brick, Plaster, Insulation, Membrane
- Only applied to new objects — never overwrites on re-sync
- Generic fallback uses Rhino layer color

### Layer visibility
- Must walk full parent chain — `layer.IsVisible` only checks own flag
- Use `_get_visible_layer_indices()` helper (checks parents via `ParentLayerId`)

## Blender addon install
- Zip lives at `D:/BlenderSync/rhino_sync.zip`
- Rebuild: `cd blender && python -c "import zipfile..."`
- **Must delete old addon folder before reinstall:** `C:/Users/parke/AppData/Roaming/Blender Foundation/Blender/5.1/scripts/addons/rhino_sync/`
- Blender caches old Python files — uninstall alone doesn't always work

## Recent exports dropdown
- Rhino writes `D:/BlenderSync/recent_exports.json` after each export
- Blender addon reads it (hardcoded path) to populate project picker dropdown

## Phases
- **Phase 1 (current):** Core pipeline — export, sync, materials, blocks
- **Phase 2:** Blender MCP server (fork ahujasid/blender-mcp) — Claude-assisted scene setup
- **Phase 3:** GN Material Controllers — per-object material sliders via Geometry Nodes
- **Phase 4:** Polish — texture libraries, animation, batch renders

## Common issues
- Rhino module caching: `importlib.reload()` handles this, but restart editor if stuck
- Blender addon caching: delete addon folder manually, restart Blender
- `doc.Path` is full path not directory — always use `os.path.dirname()`
- String GUID → `System.Guid()` conversion needed for RhinoCommon lookups
- Parent layer visibility: `layer.IsVisible` doesn't check parents
