# -*- coding: utf-8 -*-
"""Build manifest data from Rhino document state."""

import json
import os
import time

import Rhino
import scriptcontext as sc

# Max recursion depth for nested blocks (prevent infinite loops)
_MAX_BLOCK_DEPTH = 10


def _print(msg):
    """Print with prefix."""
    print("[BlenderSync] {}".format(msg))


def _get_visible_layers():
    """Return list of visible layer dicts using RhinoCommon directly (faster than rs)."""
    layers = []
    for layer in sc.doc.Layers:
        if layer.IsDeleted:
            continue
        if not layer.IsVisible:
            continue
        # Check if layer has any objects (skip empties)
        # Use RhinoCommon — no rhinoscriptsyntax overhead
        layers.append({
            "path": layer.FullPath,
            "color": [layer.Color.R, layer.Color.G, layer.Color.B],
            "visible": True,
        })
    return layers


def _collect_all_objects():
    """Walk all doc objects once, classify by layer. Much faster than per-layer queries.

    Returns:
        dict: {layer_full_path: {"breps": [obj_id, ...], "blocks": [obj_id, ...]}}
    """
    result = {}
    visible_layers = set()

    # Pre-build visible layer lookup
    for layer in sc.doc.Layers:
        if not layer.IsDeleted and layer.IsVisible:
            visible_layers.add(layer.Index)

    for rhino_obj in sc.doc.Objects:
        # Skip hidden objects
        if rhino_obj.IsHidden:
            continue
        # Skip objects on hidden layers
        layer_idx = rhino_obj.Attributes.LayerIndex
        if layer_idx not in visible_layers:
            continue

        layer = sc.doc.Layers[layer_idx]
        layer_path = layer.FullPath

        if layer_path not in result:
            result[layer_path] = {"breps": [], "blocks": []}

        obj_type = rhino_obj.ObjectType

        if obj_type in (
            Rhino.DocObjects.ObjectType.Brep,
            Rhino.DocObjects.ObjectType.Surface,
            Rhino.DocObjects.ObjectType.Extrusion,
        ):
            result[layer_path]["breps"].append(rhino_obj)
        elif obj_type == Rhino.DocObjects.ObjectType.InstanceReference:
            result[layer_path]["blocks"].append(rhino_obj)

    return result


def _object_entry(rhino_obj, layer_path):
    """Build a manifest entry dict for one Rhino object (RhinoCommon, no rs)."""
    guid = str(rhino_obj.Id)
    name = rhino_obj.Name or ""
    mesh_file = "meshes/{}.obj".format(guid)

    bb = rhino_obj.Geometry.GetBoundingBox(True)
    bbox = None
    if bb.IsValid:
        bbox = {
            "min": [bb.Min.X, bb.Min.Y, bb.Min.Z],
            "max": [bb.Max.X, bb.Max.Y, bb.Max.Z],
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


def _collect_definition_geometry(idef, depth=0):
    """Recursively collect meshable geometry from a block definition.

    Returns list of (geometry, xform, layer_name) tuples in definition-local coords.
    Layer name is the internal layer of the sub-object (for material mapping).
    """
    if depth > _MAX_BLOCK_DEPTH:
        _print("  Warning: max block nesting depth reached for '{}'".format(idef.Name))
        return []

    pieces = []
    try:
        for rhino_obj in idef.GetObjects():
            if isinstance(rhino_obj, Rhino.DocObjects.InstanceObject):
                nested_idef = rhino_obj.InstanceDefinition
                nested_xform = rhino_obj.InstanceXform
                for geom, child_xform, layer_name in _collect_definition_geometry(nested_idef, depth + 1):
                    composed = nested_xform * child_xform
                    pieces.append((geom, composed, layer_name))
            else:
                geom = rhino_obj.Geometry
                if isinstance(geom, Rhino.Geometry.Extrusion):
                    geom = geom.ToBrep(True)
                if isinstance(geom, (Rhino.Geometry.Brep, Rhino.Geometry.Surface)):
                    # Get internal layer name for material mapping
                    layer_idx = rhino_obj.Attributes.LayerIndex
                    layer_name = sc.doc.Layers[layer_idx].FullPath
                    pieces.append((geom.Duplicate(), Rhino.Geometry.Transform.Identity, layer_name))
    except Exception as e:
        _print("  Warning: error reading block '{}': {}".format(idef.Name, e))

    return pieces


def _collect_block_definitions():
    """Find all in-use block definitions and their instances.

    Returns:
        dict: {def_name: {"geometry": [...], "instances": [...]}}
    """
    definitions = {}

    visible_layers = set()
    for layer in sc.doc.Layers:
        if not layer.IsDeleted and layer.IsVisible:
            visible_layers.add(layer.Index)

    for idef in sc.doc.InstanceDefinitions:
        if idef.IsDeleted:
            continue

        try:
            refs = idef.GetReferences(0)
        except Exception:
            continue

        if not refs or len(refs) == 0:
            continue

        _print("  Processing block: '{}' ({} refs)".format(idef.Name, len(refs)))

        # Collect meshable geometry from the definition
        def_objects = _collect_definition_geometry(idef)
        if not def_objects:
            _print("    No meshable geometry, skipping")
            continue

        # Collect visible instance placements
        instances = []
        for inst_obj in refs:
            if inst_obj.IsHidden:
                continue
            layer_idx = inst_obj.Attributes.LayerIndex
            if layer_idx not in visible_layers:
                continue

            layer = sc.doc.Layers[layer_idx]
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
            _print("    {} pieces, {} visible instances".format(
                len(def_objects), len(instances)))

    return definitions


def build_manifest(quality="preview"):
    """Build the full manifest dict from the active Rhino document.

    Args:
        quality: "preview" or "final"

    Returns:
        dict with keys: source_file, exported_at, quality, units, layers,
                        objects, block_definitions, block_instances
    """
    doc = Rhino.RhinoDoc.ActiveDoc
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

    _print("Collecting layers...")
    layers = _get_visible_layers()
    _print("Found {} visible layers".format(len(layers)))

    # Single pass over all objects — much faster than per-layer rs queries
    _print("Collecting objects...")
    objects_by_layer = _collect_all_objects()

    objects = []
    total_breps = 0
    total_blocks = 0
    for layer_path, layer_objs in objects_by_layer.items():
        for rhino_obj in layer_objs["breps"]:
            entry = _object_entry(rhino_obj, layer_path)
            objects.append(entry)
            total_breps += 1
        total_blocks += len(layer_objs["blocks"])

    _print("Found {} breps, {} block instances".format(total_breps, total_blocks))

    # Collect block definitions and instances
    _print("Scanning block definitions...")
    block_defs = _collect_block_definitions()

    block_definitions = {}
    block_instances = []
    for def_name, def_data in block_defs.items():
        # Record each sub-piece with its layer for material mapping
        pieces_info = []
        for i, (geom, xform, layer_name) in enumerate(def_data["geometry"]):
            pieces_info.append({
                "index": i,
                "mesh_file": "blocks/{}/piece_{}.obj".format(def_name, i),
                "layer": layer_name,
            })
        block_definitions[def_name] = {
            "pieces": pieces_info,
        }
        for inst in def_data["instances"]:
            block_instances.append(inst)

    _print("Manifest complete: {} objects, {} block defs, {} block instances".format(
        len(objects), len(block_definitions), len(block_instances)))

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
    """Write manifest dict to a JSON file."""
    with open(output_path, "w") as f:
        json.dump(manifest_dict, f, indent=2)
