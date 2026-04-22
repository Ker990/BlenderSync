"""Rhino Sync — N-panel UI for 3D Viewport sidebar."""

import os
import time

import bpy
from bpy.props import StringProperty, PointerProperty

from ..core.sync_engine import sync, RHINO_GUID_KEY
from ..core.manifest_reader import get_manifest_mtime


class RhinoSyncSettings(bpy.types.PropertyGroup):
    """Per-file settings stored with the .blend."""

    project_folder: StringProperty(
        name="Project Folder",
        description="Path to the _blender export folder",
        subtype='DIR_PATH',
        default="",
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

        # Project folder
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
    RHINOSYNC_OT_sync,
    VIEW3D_PT_rhino_sync,
)
