"""Material mapping — layer names to Principled BSDF presets."""

import hashlib
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


def _layer_id_color(layer_name):
    """Generate a unique, visually distinct color from a layer name.

    Uses a hash to produce deterministic HSV color with high saturation
    and medium value — like V-Ray Object ID / Enscape random colors.
    Same layer always gets the same color.
    """
    h = int(hashlib.md5(layer_name.encode()).hexdigest()[:8], 16)

    # Spread hue evenly, keep saturation high, value medium-bright
    hue = (h % 360) / 360.0
    saturation = 0.55 + (((h >> 12) % 30) / 100.0)  # 0.55–0.85
    value = 0.60 + (((h >> 20) % 25) / 100.0)        # 0.60–0.85

    # HSV to RGB
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return (r, g, b)


def _load_mapping_rules(presets_dir):
    """Load material_map.json from the presets directory."""
    map_path = os.path.join(presets_dir, "material_map.json")
    if not os.path.exists(map_path):
        return {"rules": [], "fallback": "Generic_Default"}

    with open(map_path, "r") as f:
        return json.load(f)


def _create_principled_material(name, base_color, roughness=0.5, metallic=0.0, extras=None):
    """Create a Principled BSDF material with given parameters.

    Args:
        name: material name
        base_color: (R, G, B) floats 0-1
        roughness: float 0-1
        metallic: float 0-1
        extras: dict of additional input values

    Returns:
        bpy.types.Material
    """
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (300, 0)
    mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = (
        base_color[0], base_color[1], base_color[2], 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic

    if extras:
        name_map = {
            "Transmission Weight": "Transmission Weight",
            "Ior": "IOR",
        }
        for key, val in extras.items():
            input_name = key.replace("_", " ").title()
            input_name = name_map.get(input_name, input_name)
            if input_name in bsdf.inputs:
                bsdf.inputs[input_name].default_value = val

    return mat


class MaterialMapper:
    """Maps layer names to Blender materials using keyword rules."""

    def __init__(self, presets_dir):
        mapping = _load_mapping_rules(presets_dir)
        self.rules = mapping.get("rules", [])

    def get_material_for_layer(self, layer_path, layer_color=None):
        """Return a Blender material for the given layer path.

        Priority:
        1. Keyword match from material_map.json → preset material
        2. No match → unique Layer ID color (deterministic from layer name)
        """
        layer_lower = layer_path.lower()

        # Check keyword rules first
        for rule in self.rules:
            keyword = rule["match"].lower()
            if keyword in layer_lower:
                preset_name = rule["material"]
                if preset_name in MATERIAL_PRESETS:
                    color, rough, metal, extras = MATERIAL_PRESETS[preset_name]
                    return _create_principled_material(
                        preset_name, color, rough, metal, extras)

        # No match — generate Layer ID material
        # Use the layer name as the material name so each layer is unique
        safe_name = "Layer_{}".format(layer_path.replace("::", "_").replace(" ", ""))
        mat = bpy.data.materials.get(safe_name)
        if mat is not None:
            return mat

        color = _layer_id_color(layer_path)
        return _create_principled_material(safe_name, color, roughness=0.5)
