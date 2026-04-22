"""Rhino Sync — N-panel UI for 3D Viewport sidebar."""

import json
import os
import time

import bpy
from bpy.props import StringProperty, EnumProperty, PointerProperty

from ..core.sync_engine import sync, RHINO_GUID_KEY
from ..core.manifest_reader import get_manifest_mtime


# Path to shared recent_exports.json (written by Rhino exporter)
_RECENT_EXPORTS_PATH = "D:/BlenderSync/recent_exports.json"


def _load_recent_exports():
    """Load recent exports list from shared JSON file."""
    if not os.path.exists(_RECENT_EXPORTS_PATH):
        return []
    try:
        with open(_RECENT_EXPORTS_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _recent_exports_enum(self, context):
    """Dynamic enum items for the recent exports dropdown."""
    recent = _load_recent_exports()
    items = [("NONE", "Select a project...", "", 0)]
    for i, entry in enumerate(recent):
        export_dir = entry.get("export_dir", "")
        source = entry.get("source_file", "")
        # Show the Rhino filename as the label
        label = os.path.basename(source) if source else os.path.basename(export_dir)
        desc = export_dir
        items.append((export_dir, label, desc, i + 1))
    return items


class RhinoSyncSettings(bpy.types.PropertyGroup):
    """Per-file settings stored with the .blend."""

    project_folder: StringProperty(
        name="Project Folder",
        description="Path to the _blender export folder",
        subtype='DIR_PATH',
        default="",
    )
    recent_project: EnumProperty(
        name="Recent Projects",
        description="Recently exported Rhino projects",
        items=_recent_exports_enum,
    )
    last_sync_time: StringProperty(
        name="Last Sync",
        default="",
    )
    last_sync_summary: StringProperty(
        name="Last Sync Summary",
        default="",
    )
    object_count: bpy.props.IntProperty(name="Objects", default=0)
    layer_count: bpy.props.IntProperty(name="Layers", default=0)


class RHINOSYNC_OT_pick_recent(bpy.types.Operator):
    """Set project folder from recent exports list"""

    bl_idname = "rhino_sync.pick_recent"
    bl_label = "Use Selected Project"
    bl_description = "Set the project folder to the selected recent export"

    def execute(self, context):
        settings = context.scene.rhino_sync
        selected = settings.recent_project
        if selected and selected != "NONE":
            settings.project_folder = selected
            self.report({'INFO'}, "Project set to: {}".format(
                os.path.basename(selected)))
        return {'FINISHED'}


class RHINOSYNC_OT_sync(bpy.types.Operator):
    """Sync geometry from Rhino export folder"""

    bl_idname = "rhino_sync.sync"
    bl_label = "Sync Now"
    bl_description = "Import or update geometry from the Rhino export folder"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.rhino_sync

        folder = bpy.path.abspath(settings.project_folder)
        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "Set a valid project folder first")
            return {'CANCELLED'}

        manifest_path = os.path.join(folder, "manifest.json")
        if not os.path.exists(manifest_path):
            self.report({'ERROR'}, "No manifest.json found in project folder")
            return {'CANCELLED'}

        # Find presets directory (shipped with addon)
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        presets_dir = os.path.join(addon_dir, "presets")

        try:
            result = sync(manifest_path, presets_dir)
        except Exception as e:
            self.report({'ERROR'}, "Sync failed: {}".format(e))
            return {'CANCELLED'}

        # Update settings
        settings.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
        settings.object_count = result.total_objects
        settings.last_sync_summary = result.summary()

        self.report({'INFO'}, "Synced: {} updated, {} added, {} removed".format(
            result.updated, result.added, result.removed))

        return {'FINISHED'}


class VIEW3D_PT_rhino_sync(bpy.types.Panel):
    """Rhino Sync panel in the 3D Viewport sidebar."""

    bl_idname = "VIEW3D_PT_rhino_sync"
    bl_label = "Rhino Sync"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Rhino Sync"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.rhino_sync

        # Recent projects picker
        box = layout.box()
        box.label(text="Recent Exports:", icon='FILE_FOLDER')
        box.prop(settings, "recent_project", text="")
        box.operator("rhino_sync.pick_recent", icon='CHECKMARK')

        layout.separator()

        # Manual project folder (fallback)
        layout.prop(settings, "project_folder", text="Project")

        # Check for updates
        folder = bpy.path.abspath(settings.project_folder)
        manifest_path = os.path.join(folder, "manifest.json") if folder else ""
        has_manifest = os.path.exists(manifest_path) if manifest_path else False

        # Sync button
        row = layout.row()
        row.scale_y = 1.5
        row.enabled = has_manifest
        row.operator("rhino_sync.sync", icon='FILE_REFRESH')

        # Status
        if settings.last_sync_time:
            layout.separator()
            box = layout.box()
            box.label(text="Last sync: {}".format(settings.last_sync_time))
            box.label(text="{} objects".format(settings.object_count))

            # Show sync summary lines
            if settings.last_sync_summary:
                for line in settings.last_sync_summary.split("\n"):
                    if line.strip():
                        box.label(text=line.strip())
        elif not has_manifest and folder:
            layout.label(text="No manifest.json found", icon='ERROR')


# Classes to register (order matters — PropertyGroup before users)
classes = (
    RhinoSyncSettings,
    RHINOSYNC_OT_pick_recent,
    RHINOSYNC_OT_sync,
    VIEW3D_PT_rhino_sync,
)
