# -*- coding: utf-8 -*-
"""BlenderSync — Export Rhino geometry for Blender rendering.

Usage:
    RunPythonScript "D:/BlenderSync/rhino/blender_sync.py"
    RunPythonScript "D:/BlenderSync/rhino/blender_sync.py" final

First form exports with preview-quality meshing.
Second form exports with final (smooth) meshing.
"""

import os
import sys
import shutil
import time

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc

# Ensure our module directory is importable
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import manifest as manifest_mod
import mesh_utils

# Force reload so edits take effect without restarting Rhino
from importlib import reload
reload(manifest_mod)
reload(mesh_utils)


def _get_output_dir():
    """Determine export directory from the active document path.

    Returns:
        str: path like D:/Projects/House_blender/
        None if document is not saved
    """
    doc = Rhino.RhinoDoc.ActiveDoc
    if not doc.Path:
        print("[BlenderSync] Error: Save the Rhino file first.")
        return None

    # doc.Path is the full file path (dir + filename) in Rhino 8
    doc_dir = os.path.dirname(doc.Path)
    file_name = os.path.splitext(os.path.basename(doc.Path))[0]
    return os.path.join(doc_dir, "{}_blender".format(file_name))


def _ensure_dirs(output_dir):
    """Create output directory and meshes subfolder."""
    meshes_dir = os.path.join(output_dir, "meshes")
    if not os.path.exists(meshes_dir):
        os.makedirs(meshes_dir)
    blocks_dir = os.path.join(output_dir, "blocks")
    if not os.path.exists(blocks_dir):
        os.makedirs(blocks_dir)
    return meshes_dir


def _clean_exports(output_dir):
    """Remove old OBJ files before re-export."""
    for subdir in ("meshes", "blocks"):
        dirpath = os.path.join(output_dir, subdir)
        if os.path.exists(dirpath):
            for f in os.listdir(dirpath):
                if f.endswith(".obj"):
                    os.remove(os.path.join(dirpath, f))


def _log_recent_export(export_dir, source_file):
    """Append this export to recent_exports.json so Blender can find it."""
    import json
    recent_path = os.path.join(_script_dir, "..", "recent_exports.json")
    recent_path = os.path.normpath(recent_path)

    recent = []
    if os.path.exists(recent_path):
        try:
            with open(recent_path, "r") as f:
                recent = json.load(f)
        except (ValueError, IOError):
            recent = []

    # Build entry
    entry = {
        "export_dir": export_dir,
        "source_file": source_file,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Remove existing entry for same export_dir, add new at top
    recent = [r for r in recent if r.get("export_dir") != export_dir]
    recent.insert(0, entry)

    # Keep last 20
    recent = recent[:20]

    try:
        with open(recent_path, "w") as f:
            json.dump(recent, f, indent=2)
    except IOError:
        pass  # Non-critical — don't fail the export


def blender_sync(quality="preview"):
    """Main export function.

    Args:
        quality: "preview" or "final"
    """
    t0 = time.time()

    output_dir = _get_output_dir()
    if output_dir is None:
        return

    meshes_dir = _ensure_dirs(output_dir)

    # Build manifest
    print("[BlenderSync] Building manifest...")
    manifest_data = manifest_mod.build_manifest(quality)

    # Determine which objects need re-meshing (skip cached)
    mesh_params = mesh_utils.get_mesh_params(quality)
    exported = 0
    cached = 0
    failed = 0

    total_objs = len(manifest_data["objects"])
    for i, obj_entry in enumerate(manifest_data["objects"]):
        guid = obj_entry["guid"]
        obj_path = os.path.join(output_dir, obj_entry["mesh_file"])

        # Skip if OBJ already exists (cached from previous export)
        if os.path.exists(obj_path):
            cached += 1
            continue

        success = mesh_utils.export_object(guid, output_dir, mesh_params)
        if success:
            exported += 1
        else:
            failed += 1

        # Progress every 50 objects
        if (exported + failed) % 50 == 0:
            print("[BlenderSync]   Meshing: {}/{} (cached: {})".format(
                exported + failed + cached, total_objs, cached))

    # Remove failed objects from manifest
    manifest_data["objects"] = [
        o for o in manifest_data["objects"]
        if os.path.exists(os.path.join(output_dir, o["mesh_file"]))
    ]

    print("[BlenderSync] Objects: {} meshed, {} cached, {} failed".format(
        exported, cached, failed))

    # Export block definitions (skip if folder already has OBJs)
    print("[BlenderSync] Scanning for block instances...")
    block_defs = manifest_mod._collect_block_definitions()
    print("[BlenderSync] Found {} block definitions".format(len(block_defs)))

    blocks_exported = 0
    blocks_cached = 0
    for def_name, def_data in block_defs.items():
        # Check if this definition's pieces already exist
        def_dir = os.path.join(output_dir, "blocks", def_name)
        if os.path.isdir(def_dir) and any(f.endswith(".obj") for f in os.listdir(def_dir)):
            blocks_cached += 1
            continue

        piece_count = mesh_utils.export_block_definition(
            def_name, def_data["geometry"], output_dir, mesh_params)
        if piece_count > 0:
            blocks_exported += 1
            print("[BlenderSync]   Meshed block: '{}' ({} pieces)".format(
                def_name, piece_count))
        else:
            # Remove from manifest if no pieces exported
            manifest_data["block_definitions"].pop(def_name, None)
            manifest_data["block_instances"] = [
                inst for inst in manifest_data["block_instances"]
                if inst["definition"] != def_name
            ]

    print("[BlenderSync] Blocks: {} meshed, {} cached".format(
        blocks_exported, blocks_cached))

    # Write manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    manifest_mod.write_manifest(manifest_data, manifest_path)

    elapsed = time.time() - t0
    layer_count = len(manifest_data["layers"])
    block_inst_count = len(manifest_data.get("block_instances", []))
    print("[BlenderSync] Exported {} objects + {} block defs ({} instances) across {} layers -> {}".format(
        exported, blocks_exported, block_inst_count, layer_count, output_dir))
    if failed:
        print("[BlenderSync] {} objects skipped (meshing failed)".format(failed))
    print("[BlenderSync] Quality: {} | Time: {:.1f}s".format(quality, elapsed))

    # Log to recent_exports.json so Blender addon can find this project
    _log_recent_export(output_dir, manifest_data.get("source_file", ""))


# --- Entry point ---
if __name__ == "__main__" or True:
    quality = "preview"
    clean = False

    # Check sticky flags set by aliases
    if sc.sticky.get("blendersync_quality") == "final":
        quality = "final"
        sc.sticky["blendersync_quality"] = None

    if sc.sticky.get("blendersync_clean"):
        clean = True
        sc.sticky["blendersync_clean"] = None

    # Clean = delete all cached OBJs before export
    if clean:
        output_dir = _get_output_dir()
        if output_dir:
            print("[BlenderSync] Clean export — deleting cached meshes...")
            _clean_exports(output_dir)

    blender_sync(quality)
