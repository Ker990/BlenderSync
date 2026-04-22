"""Material mapping — layer names to Principled BSDF presets."""

import json
import os

import bpy


# Built-in material presets: name → Principled BSDF parameters
# Values: (base_color_rgb, roughness, metallic, extras_dict)
MATERIAL_PRESETS = {
    "Concrete_Default": ((0.50, 0.50, 0.48), 0.85, 0.0, {}),
    "Glass_Default": ((0.90, 0.95, 1.00), 0.02, 0.0, {
        "transmission_weight": 1.0,
        "ior": 1.52,
    }),
    "Wood_Default": ((0.40, 0.25, 0.12), 0.55, 0.0, {}),
    "Metal_Default": ((0.55, 0.55, 0.55), 0.35, 1.0, {}),
    "Brick_Default": ((0.60, 0.25, 0.15), 0.90, 0.0, {}),
    "Plaster_Default": ((0.85, 0.83, 0.80), 0.95, 0.0, {}),
    "Insulation_Default": ((0.85, 0.80, 0.40), 0.90, 0.0, {}),
    "Membrane_Default": ((0.30, 0.30, 0.35), 0.70, 0.0, {}),
}


def _load_mapping_rules(presets_dir):
    """Load material_map.json from the presets directory.

    Returns:
        dict with 'rules' list and 'fallback' string
    """
    map_path = os.path.join(presets_dir, "material_map.json")
    if not os.path.exists(map_path):
        return {"rules": [], "fallback": "Generic_Default"}

    with open(map_path, "r") as f:
        return json.load(f)


def _get_or_create_material(preset_name, layer_color=None):
    """Get an existing material or create one from a preset.

    Args:
        preset_name: key into MATERIAL_PRESETS, or "Generic_Default"
        layer_color: (R, G, B) 0-255 tuple for Generic fallback

    Returns:
        bpy.types.Material
    """
    # Return existing if already created
    mat = bpy.data.materials.get(preset_name)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name=preset_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    # Create Principled BSDF
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)

    # Create output
    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300, 0)
    mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    # Apply preset values
    if preset_name in MATERIAL_PRESETS:
        color_rgb, roughness, metallic, extras = MATERIAL_PRESETS[preset_name]
        bsdf.inputs["Base Color"].default_value = (
            color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic

        for key, val in extras.items():
            input_name = key.replace("_", " ").title()
            # Handle specific Blender 4.x+ input name mappings
            name_map = {
                "Transmission Weight": "Transmission Weight",
                "Ior": "IOR",
            }
            input_name = name_map.get(input_name, input_name)
            if input_name in bsdf.inputs:
                bsdf.inputs[input_name].default_value = val
    else:
        # Generic fallback — use layer color if provided
        if layer_color:
            r, g, b = layer_color[0] / 255.0, layer_color[1] / 255.0, layer_color[2] / 255.0
        else:
            r, g, b = 0.7, 0.7, 0.7
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.5

    return mat


class MaterialMapper:
    """Maps layer names to Blender materials using keyword rules."""

    def __init__(self, presets_dir):
        """Initialize with path to the presets directory.

        Args:
            presets_dir: path containing material_map.json
        """
        mapping = _load_mapping_rules(presets_dir)
        self.rules = mapping.get("rules", [])
        self.fallback = mapping.get("fallback", "Generic_Default")

    def get_material_for_layer(self, layer_path, layer_color=None):
        """Return a Blender material for the given layer path.

        Matches layer path against rules (case-insensitive substring).
        First match wins. Falls back to Generic with layer color.

        Args:
            layer_path: full Rhino layer path like "Level 1 :: Walls :: Exterior"
            layer_color: (R, G, B) 0-255 tuple or None

        Returns:
            bpy.types.Material
        """
        layer_lower = layer_path.lower()

        for rule in self.rules:
            keyword = rule["match"].lower()
            if keyword in layer_lower:
                return _get_or_create_material(rule["material"])

        # Fallback — use layer color for Generic
        return _get_or_create_material(self.fallback, layer_color)
