"""Rhino Sync — Blender addon for importing and syncing Rhino geometry.

Reads BlenderSync export packages (manifest.json + OBJ meshes),
builds Blender collections from Rhino layers, and supports stable
re-sync via GUID matching.
"""

bl_info = {
    "name": "Rhino Sync",
    "author": "Parker Gillespie",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Rhino Sync",
    "description": "Import and sync geometry from Rhino with layer-based material mapping",
    "category": "Import-Export",
}

import bpy
from bpy.props import PointerProperty

from .ui.panel import (
    RhinoSyncSettings,
    RHINOSYNC_OT_sync,
    VIEW3D_PT_rhino_sync,
)


classes = (
    RhinoSyncSettings,
    RHINOSYNC_OT_sync,
    VIEW3D_PT_rhino_sync,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rhino_sync = PointerProperty(type=RhinoSyncSettings)


def unregister():
    del bpy.types.Scene.rhino_sync
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
