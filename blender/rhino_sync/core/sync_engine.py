"""Sync engine — GUID matching, mesh swap, collection builder."""

import os
import time
from mathutils import Matrix

import bpy

from .manifest_reader import read_manifest, Manifest
from .material_mapper import MaterialMapper


# Custom property key used to tag objects with their Rhino GUID
RHINO_GUID_KEY = "rhino_guid"

# Name of the collection for removed objects
REMOVED_COLLECTION = "_Removed"


def _ensure_collection(name, parent=None):
    """Get or create a collection, linked under parent.

    Args:
        name: collection name
        parent: parent bpy.types.Collection, or None for scene root

    Returns:
        bpy.types.Collection
    """
    if parent is None:
        parent = bpy.context.scene.collection

    for child in parent.children:
        if child.name == name:
            return child

    col = bpy.data.collections.new(name=name)
    parent.children.link(col)
    return col


def _ensure_collection_path(layer_path, separator=" :: "):
    """Create nested collection hierarchy from a layer path string.

    "Level 1 :: Walls :: Exterior" →
        Scene Collection > Level 1 > Walls > Exterior

    Returns the innermost collection.
    """
    parts = [p.strip() for p in layer_path.split(separator)]
    parent = bpy.context.scene.collection

    for part_name in parts:
        parent = _ensure_collection(part_name, parent)

    return parent


def _find_objects_by_guid():
    """Build a dict mapping rhino_guid → bpy.types.Object for all tagged objects."""
    guid_map = {}
    for obj in bpy.data.objects:
        guid = obj.get(RHINO_GUID_KEY)
        if guid:
            guid_map[guid] = obj
    return guid_map


def _import_obj_mesh(filepath):
    """Import an OBJ file and return the resulting mesh datablock.

    Imports into a temp object, steals its mesh, deletes the object.

    Returns:
        bpy.types.Mesh or None
    """
    if not os.path.exists(filepath):
        return None

    existing = set(bpy.data.objects[:])

    bpy.ops.wm.obj_import(
        filepath=filepath,
        up_axis='Z',
        forward_axis='NEGATIVE_Y',
    )

    new_objects = [o for o in bpy.data.objects if o not in existing]
    if not new_objects:
        return None

    # Take the mesh from the first imported object
    source_obj = new_objects[0]
    mesh = source_obj.data

    # Remove all imported objects (but not the mesh we're keeping)
    for obj in new_objects:
        # Unlink from all collections
        for col in obj.users_collection:
            col.objects.unlink(obj)
        if obj != source_obj:
            if obj.data and obj.data != mesh and obj.data.users == 1:
                bpy.data.meshes.remove(obj.data)
            bpy.data.objects.remove(obj, do_unlink=True)

    # Remove the source object shell, keep the mesh
    bpy.data.objects.remove(source_obj, do_unlink=True)

    return mesh


def _swap_mesh(obj, new_mesh):
    """Replace an object's mesh data, preserving materials and modifiers.

    Materials are transferred from old mesh to new mesh before swap.
    """
    old_mesh = obj.data

    # Transfer material slots to the new mesh
    for mat in old_mesh.materials:
        new_mesh.materials.append(mat)

    obj.data = new_mesh

    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def _move_to_removed(obj):
    """Hide an object and move it to the _Removed collection."""
    removed_col = _ensure_collection(REMOVED_COLLECTION)
    obj.hide_set(True)
    obj.hide_render = True

    # Unlink from current collections
    for col in obj.users_collection:
        if col != removed_col:
            col.objects.unlink(obj)

    # Link to _Removed if not already there
    if obj.name not in removed_col.objects:
        removed_col.objects.link(obj)


class SyncResult:
    """Results from a sync operation."""

    def __init__(self):
        self.updated = 0
        self.added = 0
        self.removed = 0
        self.failed = 0
        self.errors = []
        self.elapsed = 0.0

    @property
    def total_objects(self):
        return self.updated + self.added

    def summary(self):
        lines = [
            "Sync complete ({:.1f}s):".format(self.elapsed),
            "  Updated: {}".format(self.updated),
            "  Added:   {}".format(self.added),
            "  Removed: {} (hidden)".format(self.removed),
        ]
        if self.failed:
            lines.append("  Failed:  {}".format(self.failed))
        if self.errors:
            lines.append("  Errors:")
            for err in self.errors[:5]:
                lines.append("    - {}".format(err))
        return "\n".join(lines)


def sync(manifest_path, presets_dir):
    """Run a full sync from a manifest file.

    Args:
        manifest_path: path to manifest.json
        presets_dir: path to presets/ directory (for material_map.json)

    Returns:
        SyncResult
    """
    t0 = time.time()
    result = SyncResult()

    # Read manifest
    manifest = read_manifest(manifest_path)

    # Build material mapper
    mapper = MaterialMapper(presets_dir)

    # Build GUID lookup of existing objects
    existing_guids = _find_objects_by_guid()
    manifest_guids = manifest.guids()

    # Create collections for all layers
    layer_collections = {}
    for layer_path in manifest.layer_paths():
        layer_collections[layer_path] = _ensure_collection_path(layer_path)

    # Process each object in manifest
    for obj_entry in manifest.objects:
        guid = obj_entry["guid"]
        layer_path = obj_entry["layer"]
        obj_filepath = manifest.obj_filepath(obj_entry)
        collection = layer_collections.get(layer_path)

        if guid in existing_guids:
            # --- UPDATE existing object ---
            blender_obj = existing_guids[guid]

            new_mesh = _import_obj_mesh(obj_filepath)
            if new_mesh is None:
                result.failed += 1
                result.errors.append("Failed to import mesh for: {}".format(guid))
                continue

            new_mesh.name = blender_obj.data.name
            _swap_mesh(blender_obj, new_mesh)

            # Unhide if it was in _Removed
            blender_obj.hide_set(False)
            blender_obj.hide_render = False

            # Move to correct collection if layer changed
            if collection:
                current_cols = list(blender_obj.users_collection)
                in_correct = any(c == collection for c in current_cols)
                if not in_correct:
                    for col in current_cols:
                        col.objects.unlink(blender_obj)
                    collection.objects.link(blender_obj)

            result.updated += 1

        else:
            # --- ADD new object ---
            new_mesh = _import_obj_mesh(obj_filepath)
            if new_mesh is None:
                result.failed += 1
                result.errors.append("Failed to import mesh for new: {}".format(guid))
                continue

            obj_name = obj_entry.get("name") or guid[:8]
            new_mesh.name = obj_name
            blender_obj = bpy.data.objects.new(obj_name, new_mesh)

            # Tag with Rhino GUID
            blender_obj[RHINO_GUID_KEY] = guid

            # Link to collection
            if collection:
                collection.objects.link(blender_obj)
            else:
                bpy.context.scene.collection.objects.link(blender_obj)

            # Assign material
            layer_color = manifest.layer_color(layer_path)
            mat = mapper.get_material_for_layer(layer_path, layer_color)
            blender_obj.data.materials.append(mat)

            result.added += 1

    # --- BLOCK INSTANCES ---
    block_defs = manifest.data.get("block_definitions", {})
    block_instances = manifest.data.get("block_instances", [])

    # Import block definition meshes (one per definition, shared across instances)
    def_meshes = {}
    for def_name, def_info in block_defs.items():
        mesh_file = os.path.join(manifest.project_dir, def_info["mesh_file"])
        mesh_data = _import_obj_mesh(mesh_file)
        if mesh_data:
            mesh_data.name = "Block_{}".format(def_name)
            def_meshes[def_name] = mesh_data

    # Track block instance GUIDs
    block_instance_guids = set()

    for inst in block_instances:
        inst_id = inst.get("instance_id", "")
        def_name = inst.get("definition", "")
        layer_path = inst.get("layer", "")
        xform_list = inst.get("transform", [])
        block_instance_guids.add(inst_id)

        mesh_data = def_meshes.get(def_name)
        if mesh_data is None:
            continue

        collection = layer_collections.get(layer_path)
        if collection is None and layer_path:
            collection = _ensure_collection_path(layer_path)
            layer_collections[layer_path] = collection

        # Build 4x4 matrix from row-major flat list
        if len(xform_list) == 16:
            mat = Matrix((
                xform_list[0:4],
                xform_list[4:8],
                xform_list[8:12],
                xform_list[12:16],
            ))
        else:
            mat = Matrix.Identity(4)

        if inst_id in existing_guids:
            # Update existing block instance
            blender_obj = existing_guids[inst_id]
            # Swap mesh to current definition mesh (shared)
            if blender_obj.data != mesh_data:
                old_mesh = blender_obj.data
                blender_obj.data = mesh_data
                if old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh)
            blender_obj.matrix_world = mat
            blender_obj.hide_set(False)
            blender_obj.hide_render = False
            result.updated += 1
        else:
            # Add new block instance — linked duplicate (shared mesh)
            obj_name = "{}_{}".format(def_name, inst_id[:8])
            blender_obj = bpy.data.objects.new(obj_name, mesh_data)
            blender_obj[RHINO_GUID_KEY] = inst_id
            blender_obj.matrix_world = mat

            if collection:
                collection.objects.link(blender_obj)
            else:
                bpy.context.scene.collection.objects.link(blender_obj)

            # Material from layer
            layer_color = manifest.layer_color(layer_path)
            mat_bl = mapper.get_material_for_layer(layer_path, layer_color)
            if len(blender_obj.data.materials) == 0:
                blender_obj.data.materials.append(mat_bl)

            result.added += 1

    # Combine all manifest GUIDs (regular + block instances)
    all_manifest_guids = manifest_guids | block_instance_guids

    # Handle removed objects (in existing but not in manifest)
    for guid, obj in existing_guids.items():
        if guid not in all_manifest_guids:
            _move_to_removed(obj)
            result.removed += 1

    result.elapsed = time.time() - t0
    return result
