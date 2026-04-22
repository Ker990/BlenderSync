# -*- coding: utf-8 -*-
"""NURBS-to-mesh conversion and OBJ writer for BlenderSync."""

import os
import System

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc


def get_mesh_params(quality):
    """Return MeshingParameters for the given quality level.

    Args:
        quality: "preview" or "final"

    Returns:
        Rhino.Geometry.MeshingParameters
    """
    mp = Rhino.Geometry.MeshingParameters()
    mp.SimplePlanes = True  # Critical — flat surfaces get minimal tris
    mp.JaggedSeams = False
    mp.ComputeNormals = True

    if quality == "final":
        mp.Tolerance = 0.001          # ~0.3mm
        mp.RelativeTolerance = 0.1
        mp.RefineAngle = 0.15         # ~8.5 degrees — smooth curves
        mp.MinimumEdgeLength = 0.003  # ~1mm floor
        mp.MaximumEdgeLength = 10.0   # ~3m ceiling
        mp.GridAspectRatio = 4.0
        mp.GridMinCount = 1
        mp.GridMaxCount = 256
        mp.GridAngle = 0.15
        mp.RefineGrid = True
    else:
        mp.Tolerance = 0.01           # ~3mm
        mp.RelativeTolerance = 0.5
        mp.RefineAngle = 0.5          # ~28 degrees
        mp.MinimumEdgeLength = 0.01   # ~3mm floor
        mp.MaximumEdgeLength = 30.0   # ~10m ceiling
        mp.GridAspectRatio = 6.0
        mp.GridMinCount = 0
        mp.GridMaxCount = 64

    return mp


def brep_to_mesh(obj_id, mesh_params):
    """Convert a Brep/Extrusion to a single joined Mesh.

    Args:
        obj_id: Rhino object GUID
        mesh_params: Rhino.Geometry.MeshingParameters

    Returns:
        Rhino.Geometry.Mesh or None
    """
    # Convert string GUID to System.Guid for lookup
    if isinstance(obj_id, str):
        guid = System.Guid(obj_id)
    else:
        guid = obj_id
    rhino_obj = sc.doc.Objects.FindId(guid)
    if rhino_obj is None:
        return None

    geom = rhino_obj.Geometry

    # Handle extrusions — convert to Brep first
    if isinstance(geom, Rhino.Geometry.Extrusion):
        geom = geom.ToBrep(True)

    if not isinstance(geom, Rhino.Geometry.Brep):
        return None

    meshes = Rhino.Geometry.Mesh.CreateFromBrep(geom, mesh_params)
    if not meshes or len(meshes) == 0:
        return None

    # Join all face meshes into one
    joined = Rhino.Geometry.Mesh()
    for m in meshes:
        joined.Append(m)

    joined.Normals.ComputeNormals()
    joined.Compact()
    return joined


def write_obj(mesh, filepath):
    """Write a Rhino Mesh to an OBJ file with normals.

    Args:
        mesh: Rhino.Geometry.Mesh
        filepath: output .obj path

    Returns:
        True on success, False on failure
    """
    try:
        vertices = mesh.Vertices
        normals = mesh.Normals
        faces = mesh.Faces

        lines = []
        lines.append("# BlenderSync OBJ export")

        # Vertices
        for i in range(vertices.Count):
            v = vertices[i]
            lines.append("v {:.6f} {:.6f} {:.6f}".format(v.X, v.Y, v.Z))

        # Normals
        for i in range(normals.Count):
            n = normals[i]
            lines.append("vn {:.4f} {:.4f} {:.4f}".format(n.X, n.Y, n.Z))

        # Faces (OBJ is 1-indexed)
        for i in range(faces.Count):
            face = faces[i]
            if face.IsQuad:
                lines.append("f {0}//{0} {1}//{1} {2}//{2} {3}//{3}".format(
                    face.A + 1, face.B + 1, face.C + 1, face.D + 1))
            else:
                lines.append("f {0}//{0} {1}//{1} {2}//{2}".format(
                    face.A + 1, face.B + 1, face.C + 1))

        dir_path = os.path.dirname(filepath)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        with open(filepath, "w") as f:
            f.write("\n".join(lines))

        return True
    except Exception as e:
        print("[BlenderSync] OBJ write error: {}".format(e))
        return False


def export_object(obj_id, output_dir, mesh_params):
    """Mesh a single Rhino object and write it as OBJ.

    Args:
        obj_id: Rhino object GUID
        output_dir: root export directory (contains meshes/ subfolder)
        mesh_params: Rhino.Geometry.MeshingParameters

    Returns:
        True on success, False on failure
    """
    mesh = brep_to_mesh(obj_id, mesh_params)
    if mesh is None:
        return False

    guid_str = str(obj_id)
    filepath = os.path.join(output_dir, "meshes", "{}.obj".format(guid_str))
    return write_obj(mesh, filepath)


def export_block_definition(def_name, geometry_pieces, output_dir, mesh_params):
    """Mesh each sub-object in a block definition as a separate OBJ.

    Args:
        def_name: block definition name
        geometry_pieces: list of (geometry, xform, layer_name) tuples
        output_dir: root export directory
        mesh_params: Rhino.Geometry.MeshingParameters

    Returns:
        int: number of pieces successfully exported
    """
    # Create subfolder for this definition
    def_dir = os.path.join(output_dir, "blocks", def_name)
    if not os.path.exists(def_dir):
        os.makedirs(def_dir)

    exported = 0
    for i, (geom, xform, layer_name) in enumerate(geometry_pieces):
        # Transform geometry to definition-local coords (for nested blocks)
        if not xform.Equals(Rhino.Geometry.Transform.Identity):
            geom = geom.Duplicate()
            geom.Transform(xform)

        mesh = Rhino.Geometry.Mesh()

        if isinstance(geom, Rhino.Geometry.Brep):
            meshes = Rhino.Geometry.Mesh.CreateFromBrep(geom, mesh_params)
            if meshes:
                for m in meshes:
                    mesh.Append(m)
        elif isinstance(geom, Rhino.Geometry.Surface):
            brep = geom.ToBrep()
            if brep:
                meshes = Rhino.Geometry.Mesh.CreateFromBrep(brep, mesh_params)
                if meshes:
                    for m in meshes:
                        mesh.Append(m)

        if mesh.Vertices.Count == 0:
            continue

        mesh.Normals.ComputeNormals()
        mesh.Compact()

        filepath = os.path.join(def_dir, "piece_{}.obj".format(i))
        if write_obj(mesh, filepath):
            exported += 1

    return exported
