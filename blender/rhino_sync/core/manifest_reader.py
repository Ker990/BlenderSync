"""Read and validate BlenderSync manifest files."""

import json
import os


class ManifestError(Exception):
    """Raised when a manifest is invalid or unreadable."""
    pass


class Manifest:
    """Parsed manifest.json data."""

    def __init__(self, data, manifest_path):
        self.data = data
        self.manifest_path = manifest_path
        self.project_dir = os.path.dirname(manifest_path)
        self.source_file = data.get("source_file", "")
        self.exported_at = data.get("exported_at", "")
        self.quality = data.get("quality", "preview")
        self.units = data.get("units", "Feet")
        self.layers = data.get("layers", [])
        self.objects = data.get("objects", [])

    @property
    def object_count(self):
        return len(self.objects)

    @property
    def layer_count(self):
        return len(self.layers)

    def obj_filepath(self, obj_entry):
        """Return absolute path to an object's OBJ file."""
        return os.path.join(self.project_dir, obj_entry["mesh_file"])

    def guids(self):
        """Return set of all object GUIDs in this manifest."""
        return {o["guid"] for o in self.objects}

    def layer_paths(self):
        """Return list of unique layer paths."""
        return [l["path"] for l in self.layers]

    def layer_color(self, layer_path):
        """Return (R, G, B) tuple for a layer, or None."""
        for l in self.layers:
            if l["path"] == layer_path:
                return tuple(l["color"])
        return None


def read_manifest(manifest_path):
    """Read and validate a manifest.json file.

    Args:
        manifest_path: absolute path to manifest.json

    Returns:
        Manifest object

    Raises:
        ManifestError if file is missing, malformed, or invalid
    """
    if not os.path.exists(manifest_path):
        raise ManifestError("Manifest not found: {}".format(manifest_path))

    try:
        with open(manifest_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise ManifestError("Failed to read manifest: {}".format(e))

    # Validate required fields
    if "objects" not in data:
        raise ManifestError("Manifest missing 'objects' field")
    if "layers" not in data:
        raise ManifestError("Manifest missing 'layers' field")

    # Validate each object has required fields
    for i, obj in enumerate(data["objects"]):
        for key in ("guid", "layer", "mesh_file"):
            if key not in obj:
                raise ManifestError(
                    "Object {} missing required field '{}'".format(i, key))

    return Manifest(data, manifest_path)


def get_manifest_mtime(manifest_path):
    """Return modification time of manifest file, or 0 if not found."""
    try:
        return os.path.getmtime(manifest_path)
    except OSError:
        return 0
