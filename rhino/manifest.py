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
    """Return Rhino object IDs on a layer that are Breps, extrusions, or block instances."""
    all_objs = rs.ObjectsByLayer(layer_path) or []
    breps = []
    blocks = []
    for obj_id in all_objs:
        if rs.IsObjectHidden(obj_id):
            continue
        obj_type = rs.ObjectType(obj_id)
        # 8 = Surface, 16 = Polysurface, 1073741824 = Extrusion
        if obj_type in (8, 16, 1073741824):
            breps.append(obj_id)
        # 4096 = Block Instance
        elif obj_type == 4096:
            blocks.append(obj_id)
    return breps, blocks


def _object_entry(obj_id, layer_path):
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


def _xform_to_list(xform):
    """Convert a Rhino Transform to a flat 16-element list (row-major)."""
    return [
        xform.M00, xform.M01, xform.M02, xform.M03,
        xform.M10, xform.M11, xform.M12, xform.M13,
        xform.M20, xform.M21, xform.M22, xform.M23,
        xform.M30, xform.M31, xform.M32, xform.M33,
    ]


def _collect_block_definitions():
    """Find all in-use block definitions and their instances.

    Returns:
        dict: {def_name: {"objects": [rhino_obj, ...], "instances": [instance_data, ...]}}
    """
    definitions = {}

    for idef in sc.doc.InstanceDefinitions:
        if idef.IsDeleted:
            continue
        refs = idef.GetReferences(0)  # top-level references only
        if not refs or len(refs) == 0:
            continue

        # Collect meshable geometry from the definition (recursive for nested blocks)
        def_objects = _collect_definition_geometry(idef)
        if not def_objects:
            continue

        # Collect instance placements
        instances = []
        for inst_obj in refs:
            if inst_obj.IsHidden:
                continue
            layer_idx = inst_obj.Attributes.LayerIndex
            layer = sc.doc.Layers[layer_idx]
            if not layer.IsVisible:
                continue

            instances.append({
                "instance_id": str(inst_obj.Id),
                "definition": idef.Name,
                "transform": _xform_to_list(inst_obj.InstanceXform),
                "layer": layer.FullPath,
            })

        if instances:
            definitions[idef.Name] = {
                "geometry": def_objects,
                "instances": instances,
            }

    return definitions


def _collect_definition_geometry(idef):
    """Recursively collect meshable geometry from a block definition.

    Returns list of (geometry, xform) tuples in definition-local coords.
    """
    pieces = []
    for rhino_obj in idef.GetObjects():
        if isinstance(rhino_obj, Rhino.DocObjects.InstanceObject):
            # Nested block — recurse and compose transform
            nested_idef = rhino_obj.InstanceDefinition
            nested_xform = rhino_obj.InstanceXform
            for geom, child_xform in _collect_definition_geometry(nested_idef):
                composed = nested_xform * child_xform
                pieces.append((geom, composed))
        else:
            geom = rhino_obj.Geometry
            if isinstance(geom, Rhino.Geometry.Extrusion):
                geom = geom.ToBrep(True)
            if isinstance(geom, (Rhino.Geometry.Brep, Rhino.Geometry.Surface)):
                pieces.append((geom.Duplicate(), Rhino.Geometry.Transform.Identity))
    return pieces


def build_manifest(quality="preview"):
    """Build the full manifest dict from the active Rhino document.

    Args:
        quality: "preview" or "final"

    Returns:
        dict with keys: source_file, exported_at, quality, units, layers,
                        objects, block_definitions, block_instances
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

    # Collect regular objects and block instances per layer
    objects = []
    block_instance_ids = set()  # track which instances we already found via layers

    for layer_info in layers:
        layer_path = layer_info["path"]
        breps, blocks = _get_exportable_objects(layer_path)
        for obj_id in breps:
            entry = _object_entry(obj_id, layer_path)
            objects.append(entry)
        for obj_id in blocks:
            block_instance_ids.add(str(obj_id))

    # Collect block definitions and instances
    block_defs = _collect_block_definitions()

    block_definitions = {}
    block_instances = []
    for def_name, def_data in block_defs.items():
        block_definitions[def_name] = {
            "mesh_file": "blocks/{}.obj".format(def_name),
        }
        for inst in def_data["instances"]:
            block_instances.append(inst)

    return {
        "source_file": source_file,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "quality": quality,
        "units": units,
        "layers": layers,
        "objects": objects,
        "block_definitions": block_definitions,
        "block_instances": block_instances,
    }


def write_manifest(manifest_dict, output_path):
    """Write manifest dict to a JSON file.

    Args:
        manifest_dict: dict from build_manifest()
        output_path: full path to manifest.json
    """
    with open(output_path, "w") as f:
        json.dump(manifest_dict, f, indent=2)
