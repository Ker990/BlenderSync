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
    return meshes_dir


def _clean_meshes(meshes_dir):
    """Remove old OBJ files before re-export."""
    if os.path.exists(meshes_dir):
        for f in os.listdir(meshes_dir):
            if f.endswith(".obj"):
                os.remove(os.path.join(meshes_dir, f))


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
    _clean_meshes(meshes_dir)

    # Build manifest
    print("[BlenderSync] Building manifest...")
    manifest_data = manifest_mod.build_manifest(quality)

    # Mesh and export each object
    mesh_params = mesh_utils.get_mesh_params(quality)
    total = len(manifest_data["objects"])
    exported = 0
    failed = 0

    for i, obj_entry in enumerate(manifest_data["objects"]):
        guid = obj_entry["guid"]

        success = mesh_utils.export_object(guid, output_dir, mesh_params)
        if success:
            exported += 1
        else:
            failed += 1
            print("[BlenderSync]   Skipped: {} (meshing failed)".format(
                obj_entry.get("name", guid)))

    # Remove failed objects from manifest
    manifest_data["objects"] = [
        o for o in manifest_data["objects"]
        if os.path.exists(os.path.join(output_dir, o["mesh_file"]))
    ]

    # Write manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    manifest_mod.write_manifest(manifest_data, manifest_path)

    elapsed = time.time() - t0
    layer_count = len(manifest_data["layers"])
    print("[BlenderSync] Exported {} objects across {} layers -> {}".format(
        exported, layer_count, output_dir))
    if failed:
        print("[BlenderSync] {} objects skipped (meshing failed)".format(failed))
    print("[BlenderSync] Quality: {} | Time: {:.1f}s".format(quality, elapsed))


# --- Entry point ---
if __name__ == "__main__" or True:
    # Detect quality from Rhino command line arguments
    # Usage: RunPythonScript "path/blender_sync.py" final
    quality = "preview"

    # Check if "final" was passed (Rhino doesn't have clean arg passing,
    # so we check sc.sticky for a flag set by the alias)
    if sc.sticky.get("blendersync_quality") == "final":
        quality = "final"
        sc.sticky["blendersync_quality"] = None  # reset

    blender_sync(quality)
