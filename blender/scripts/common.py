"""Shared Blender helpers for ReaVector product geometry (headless-safe).

Run inside Blender:  blender --background --python build_product.py -- --type bottle ...
"""
from __future__ import annotations

import math
import os


def clear_scene():
    import bpy
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def _set_input(bsdf, name, value):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def make_material(name, color=(0.8, 0.8, 0.85, 1.0), metallic=0.0, roughness=0.4,
                  transmission=0.0, image_path=None):
    import bpy
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    _set_input(bsdf, "Base Color", color)
    _set_input(bsdf, "Metallic", metallic)
    _set_input(bsdf, "Roughness", roughness)
    # Blender 4 uses "Transmission Weight"; 3.x uses "Transmission"
    _set_input(bsdf, "Transmission Weight", transmission)
    _set_input(bsdf, "Transmission", transmission)
    if image_path and os.path.isfile(image_path):
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(image_path, check_existing=True)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def lathe(name, profile, segments=64):
    """Revolve a (radius, z) profile around Z into a mesh object."""
    import bmesh
    import bpy

    bm = bmesh.new()
    verts = [bm.verts.new((max(1e-4, r), 0.0, z)) for r, z in profile]
    edges = [bm.edges.new((verts[i], verts[i + 1])) for i in range(len(verts) - 1)]
    bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1),
                   dvec=(0, 0, 0), angle=2 * math.pi, steps=segments)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.normal_update()
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def box(name, sx=0.1, sy=0.05, sz=0.2):
    import bpy
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (sx, sy, sz)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def cylinder(name, radius=0.04, depth=0.2, vertices=64):
    import bpy
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=vertices)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def uv_cylindrical(obj, z_min=None, z_max=None):
    """Assign cylindrical UVs (u=angle, v=height) for label mapping."""
    import bpy
    me = obj.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uv = me.uv_layers.active.data
    zs = [v.co.z for v in me.vertices]
    lo = z_min if z_min is not None else min(zs)
    hi = z_max if z_max is not None else max(zs)
    span = max(1e-6, hi - lo)
    for poly in me.polygons:
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            u = (math.atan2(v.y, v.x) / (2 * math.pi)) + 0.5
            vv = (v.z - lo) / span
            uv[li].uv = (u, vv)


def apply_label(obj, image_path):
    uv_cylindrical(obj)
    obj.data.materials.clear()
    obj.data.materials.append(make_material("label", image_path=image_path, roughness=0.55))


def export_glb(path, objects=None):
    import bpy
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in (objects or bpy.context.scene.objects):
        if o.type == "MESH":
            o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True)
    return path