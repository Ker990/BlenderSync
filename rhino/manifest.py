# -*- coding: utf-8 -*-
"""Build manifest data from Rhino document state."""

import json
import os
import time

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc


def _layer_color_rgb(layer_full_path):
    """Return (R, G, B) tuple for a layer's display color."""
    color = rs.LayerColor(layer_full_path)
    return (color.R, color.G, color.B)


def _get_visible_layers():
    """Return list of visible layer dicts with path, color, visibility."""
    layers = []
    for layer_path in rs.LayerNames():
        if not rs.IsLayerVisible(layer_path):
            continue
        if rs.IsLayerEmpty(layer_path):
            continue
        layers.append({
            "path": layer_path,
            "color": list(_layer_color_rgb(layer_path)),
            "visible": True,
        })
    return layers


def _get_exportable_objects(layer_path):
    """Return Rhino object IDs on a layer that are Breps or extrusions."""
    all_objs = rs.ObjectsByLayer(layer_path) or []
    exportable = []
    for obj_id in all_objs:
        if rs.IsObjectHidden(obj_id):
            continue
        obj_type = rs.ObjectType(obj_id)
        # 8 = Surface, 16 = Polysurface, 1073741824 = Extrusion
        if obj_type in (8, 16, 1073741824):
            exportable.append(obj_id)
    return exportable


def _object_entry(obj_id, layer_path, meshes_dir):
    """Build a manifest entry dict for one Rhino object."""
    guid = str(obj_id)
    name = rs.ObjectName(obj_id) or ""
    mesh_file = "meshes/{}.obj".format(guid)

    bb = rs.BoundingBox(obj_id)
    bbox = None
    if bb:
        bbox = {
            "min": [bb[0].X, bb[0].Y, bb[0].Z],
            "max": [bb[6].X, bb[6].Y, bb[6].Z],
        }

    return {
        "guid": guid,
        "name": name,
        "layer": layer_path,
        "mesh_file": mesh_file,
        "bbox": bbox,
    }


def build_manifest(quality="preview"):
    """Build the full manifest dict from the active Rhino document.

    Args:
        quality: "preview" or "final"

    Returns:
        dict with keys: source_file, exported_at, quality, units, layers, objects
    """
    doc = Rhino.RhinoDoc.ActiveDoc
    # doc.Path is the full file path (dir + filename) in Rhino 8
    if doc.Path:
        source_file = doc.Path
    else:
        source_file = doc.Name or "Untitled"

    unit_system = doc.ModelUnitSystem
    units_map = {
        Rhino.UnitSystem.Feet: "Feet",
        Rhino.UnitSystem.Inches: "Inches",
        Rhino.UnitSystem.Meters: "Meters",
        Rhino.UnitSystem.Millimeters: "Millimeters",
    }
    units = units_map.get(unit_system, str(unit_system))

    layers = _get_visible_layers()

    objects = []
    for layer_info in layers:
        layer_path = layer_info["path"]
        obj_ids = _get_exportable_objects(layer_path)
        for obj_id in obj_ids:
            entry = _object_entry(obj_id, layer_path, "meshes")
            objects.append(entry)

    return {
        "source_file": source_file,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "quality": quality,
        "units": units,
        "layers": layers,
        "objects": objects,
    }


def write_manifest(manifest_dict, output_path):
    """Write manifest dict to a JSON file.

    Args:
        manifest_dict: dict from build_manifest()
        output_path: full path to manifest.json
    """
    with open(output_path, "w") as f:
        json.dump(manifest_dict, f, indent=2)
