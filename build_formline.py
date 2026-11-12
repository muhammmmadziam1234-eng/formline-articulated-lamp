"""Build and render Formline with Blender 4.5.

    blender --background --factory-startup --python build_formline.py
    blender --background --factory-startup --python build_formline.py -- --build-only
"""
from __future__ import annotations

import argparse
from itertools import product
from math import cos, pi, radians, sin
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
POSE = {
    "Shoulder tilt": (-28.0, -44.0, -14.0, "Lower linkage tilt from vertical"),
    "Elbow bend": (94.0, 69.0, 107.0, "Upper linkage angle relative to the lower linkage"),
    "Head pitch": (-59.0, -90.0, -38.0, "Shade pitch relative to the upper linkage"),
}
LOWER = 1.72
UPPER = 1.76
AXIS = Vector((0, 1, 0))
RAIL_Y = (.237, .122)
CABLE_Y = .397


def collection(name):
    group = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(group)
    return group


def place(obj, group, parent=None, location=(0, 0, 0), rotation=(0, 0, 0)):
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    group.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = rotation
    return obj


def empty(name, group, parent=None, location=(0, 0, 0), size=.13, shape="PLAIN_AXES"):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = shape
    obj.empty_display_size = size
    return place(obj, group, parent, location)


def finish(obj, material, width=0, smooth=True):
    obj.data.materials.append(material)
    if smooth:
        for face in obj.data.polygons:
            face.use_smooth = True
    if width:
        bevel = obj.modifiers.new("Machined edge radii", "BEVEL")
        bevel.width = width
        bevel.segments = 3
        normals = obj.modifiers.new("Face-weighted normals", "WEIGHTED_NORMAL")
        normals.keep_sharp = True
        normals.weight = 45
    return obj


def material(name, color, metallic, roughness, *, grain=0, radial=False,
             anisotropy=0, emission=0, coat=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    tree = mat.node_tree
    shader = tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Anisotropic"].default_value = anisotropy
    shader.inputs["Coat Weight"].default_value = coat
    shader.inputs["Coat Roughness"].default_value = .33
    if emission:
        shader.inputs["Emission Color"].default_value = (*color, 1)
        shader.inputs["Emission Strength"].default_value = emission
    if grain or radial:
        coords = tree.nodes.new("ShaderNodeTexCoord")
        if radial:
            flatten = tree.nodes.new("ShaderNodeVectorMath")
            flatten.operation = "MULTIPLY"
            flatten.inputs[1].default_value = (1, 1, 0)
            distance = tree.nodes.new("ShaderNodeVectorMath")
            distance.operation = "LENGTH"
            frequency = tree.nodes.new("ShaderNodeMath")
            frequency.operation = "MULTIPLY"
            frequency.inputs[1].default_value = 615
            wave = tree.nodes.new("ShaderNodeMath")
            wave.operation = "SINE"
            spread = tree.nodes.new("ShaderNodeMapRange")
            spread.inputs["From Min"].default_value = -1
            spread.inputs["From Max"].default_value = 1
            spread.inputs["To Min"].default_value = roughness - .07
            spread.inputs["To Max"].default_value = roughness + .07
            tree.links.new(coords.outputs["Object"], flatten.inputs[0])
            tree.links.new(flatten.outputs["Vector"], distance.inputs[0])
            tree.links.new(distance.outputs["Value"], frequency.inputs[0])
            tree.links.new(frequency.outputs[0], wave.inputs[0])
            tree.links.new(wave.outputs[0], spread.inputs["Value"])
            tree.links.new(spread.outputs[0], shader.inputs["Roughness"])
        if grain:
            noise = tree.nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = 145
            noise.inputs["Detail"].default_value = 2
            bump = tree.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = grain
            bump.inputs["Distance"].default_value = .005
            tree.links.new(coords.outputs["Object"], noise.inputs["Vector"])
            tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    return mat


def cylinder(name, radius, depth, mat, group, parent=None, location=(0, 0, 0),
             *, axis="Z", bevel=.009, sides=96):
    rotation = (pi / 2, 0, 0) if axis == "Y" else (0, 0, 0)
    bpy.ops.mesh.primitive_cylinder_add(vertices=sides, radius=radius, depth=depth)
    obj = bpy.context.object
    obj.name = name
    place(obj, group, parent, location, rotation)
    return finish(obj, mat, bevel)


def box(name, dimensions, mat, group, parent=None, location=(0, 0, 0), bevel=.01):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = name
    for vertex in obj.data.vertices:
        for axis, dimension in enumerate(dimensions):
            vertex.co[axis] *= dimension
    place(obj, group, parent, location)
    return finish(obj, mat, bevel)


def capsule(start, end, radius_start, radius_end, steps=22):
    # Counter-clockwise planar outline. The end radii can differ.
    points = []
    for center, radius, angle in ((start, radius_start, pi), (end, radius_end, 0)):
        for index in range(steps + 1):
            theta = angle + pi * index / steps
            points.append((radius * cos(theta), center + radius * sin(theta)))
    return points


def mesh_object(name, verts, faces, group, parent=None, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    return place(obj, group, parent, location)


def bridges(first, second, count):
    return [
        (first + i, first + (i + 1) % count, second + (i + 1) % count, second + i)
        for i in range(count)
    ]


def shade_layer(name, start, end, radius, depth, z, mat, group, parent, bevel):
    outline = capsule(start, end, radius, radius, 36)
    n = len(outline)
    vertices = [(y, -x, z + level) for level in (-depth / 2, depth / 2) for x, y in outline]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += bridges(0, n, n)
    return finish(mesh_object(name, vertices, faces, group, parent), mat, bevel)


def recessed_rail(name, length, y, thick, outer, pocket, group, parent):
    perimeter = capsule(0, length, .141, .125)
    cutout = capsule(.323, length - .305, .058, .049)
    n = len(perimeter)
    side = 1 if y > 0 else -1
    back = y - side * thick / 2
    face = y + side * thick / 2
    floor = face - side * .024
    vertices = [(x, level, z) for loop, level in (
        (perimeter, back), (perimeter, face), (cutout, face), (cutout, floor)
    ) for x, z in loop]
    faces = [tuple(range(n))]
    faces += bridges(0, n, n) + bridges(n, 2 * n, n) + bridges(2 * n, 3 * n, n)
    faces += [tuple(range(3 * n, 4 * n))]
    obj = finish(mesh_object(name, vertices, faces, group, parent), outer, .008)
    obj.data.materials.append(pocket)
    obj.data.polygons[-1].material_index = 1
    return obj


def torus(name, radius, section, mat, group, parent, location, axis="Z"):
    rotation = (pi / 2, 0, 0) if axis == "Y" else (0, 0, 0)
    bpy.ops.mesh.primitive_torus_add(
        major_segments=96, minor_segments=10, major_radius=radius, minor_radius=section
    )
    obj = bpy.context.object
    obj.name = name
    place(obj, group, parent, location, rotation)
    return finish(obj, mat)


def text_label(name, text, size, mat, group, parent, location, rotation=(0, 0, 0)):
    data = bpy.data.curves.new(name, "FONT")
    data.body = text
    data.align_x = "CENTER"
    data.align_y = "CENTER"
    data.size = size
    data.space_character = 1.18
    data.materials.append(mat)
    obj = bpy.data.objects.new(name, data)
    return place(obj, group, parent, location, rotation)


def driver(pivot, rig, property_name):
    channel = pivot.driver_add("rotation_euler", 1).driver
    angle = channel.variables.new()
    angle.type = "SINGLE_PROP"
    angle.name = "angle_deg"
    angle.targets[0].id = rig
    angle.targets[0].data_path = f'["{property_name}"]'
    _, minimum, maximum, _ = POSE[property_name]
    channel.expression = f"min(max(angle_deg, {minimum}), {maximum}) * {pi / 180:.16f}"


def axle(name, group, parent, z, span, caps_y, mats, *, ring=None):
    shaft = cylinder(f"{name} | stainless axle", .077, span, mats["steel"],
                     group, parent, (0, 0, z), axis="Y")
    for side in (-1, 1):
        sign = "near" if side < 0 else "far"
        y = side * caps_y
        cylinder(f"{name} | {sign} bearing flange", .127, .023, ring or mats["gunmetal"],
                 group, parent, (0, y, z), axis="Y", bevel=.005)
        cylinder(f"{name} | {sign} flush pin cap", .095, .029, mats["steel"],
                 group, parent, (0, y + side * .013, z), axis="Y", bevel=.007)
        cylinder(f"{name} | {sign} hex socket", .029, .0025, mats["rubber"],
                 group, parent, (0, y + side * .028, z), axis="Y", bevel=0, sides=6)
        torus(f"{name} | {sign} pin groove", .070, .0017, mats["engraving"],
              group, parent, (0, y + side * .028, z), "Y")
    return shaft


def area(name, color, energy, size, group, location, target=None, *, size_y=None, parent=None):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.color = color
    data.shape = "RECTANGLE" if size_y is not None else "DISK"
    data.size = size
    if size_y is not None:
        data.size_y = size_y
    obj = bpy.data.objects.new(name, data)
    place(obj, group, parent, location)
    if target is not None:
        obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def cable_guide(name, group, parent, point, mats):
    x, y, z = point
    rail_y = RAIL_Y[0] if parent.name.startswith("Shoulder") else RAIL_Y[1]
    reach = y - rail_y
    box(f"{name} | standoff", (.043, reach, .062), mats["gunmetal"], group, parent,
        (x, (y + rail_y) / 2, z), .008)
    ring = torus(name, .029, .008, mats["steel"], group, parent, point)
    ring.scale.y = .91


def build_cable(group, base, lower, upper, wrist, mats):
    # Hinge sweeps are outside the widest bearing flange. Each control point
    # and its two tangents follow the same local frame through Hook modifiers.
    waypoints = [
        (base, (-.695, .30, .218)),
        (base, (-.737, .355, .278)),
        (base, (-.695, CABLE_Y, .392)),
        (lower, (.018, CABLE_Y, .002)),
        (lower, (.022, CABLE_Y, .290)),
        (lower, (.020, CABLE_Y, .720)),
        (lower, (.018, CABLE_Y, 1.235)),
        (lower, (.017, CABLE_Y, 1.497)),
        (lower, (-.075, CABLE_Y, 1.668)),
        (lower, (-.088, CABLE_Y, 1.792)),
        (upper, (.020, CABLE_Y, .140)),
        (upper, (.019, CABLE_Y, .332)),
        (upper, (.018, CABLE_Y, .824)),
        (upper, (.020, CABLE_Y, 1.290)),
        (upper, (.018, CABLE_Y, 1.556)),
        (upper, (.007, CABLE_Y, 1.724)),
        (wrist, (.113, .350, .076)),
        (wrist, (.233, .235, .086)),
        (wrist, (.319, .150, .087)),
    ]
    data = bpy.data.curves.new("Flexible cable | hooked Bezier", "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 12
    data.bevel_depth = .020
    data.bevel_resolution = 4
    data.use_fill_caps = True
    data.materials.append(mats["cable"])
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(waypoints) - 1)
    obj = bpy.data.objects.new("Braided power cable", data)
    place(obj, group)
    anchors = []
    bpy.context.view_layer.update()
    points = [parent.matrix_world @ Vector(local) for parent, local in waypoints]
    for index, knot in enumerate(spline.bezier_points):
        point = points[index]
        preceding = points[index - 1] if index else point
        following = points[index + 1] if index < len(points) - 1 else point
        tangent = (following - preceding).normalized()
        knot.handle_left_type = knot.handle_right_type = "FREE"
        knot.co = point
        knot.handle_left = point - tangent * (point - preceding).length * .29
        knot.handle_right = point + tangent * (following - point).length * .29
        parent, local = waypoints[index]
        anchor = empty(f"Cable anchor {index + 1:02d}", group, parent, local, .026)
        anchor.hide_set(True)
        anchors.append(anchor)
    bpy.context.view_layer.update()
    for index, anchor in enumerate(anchors):
        hook = obj.modifiers.new(f"Cable anchor {index + 1:02d}", "HOOK")
        hook.object = anchor
        hook.matrix_inverse = anchor.matrix_world.inverted()
        hook.vertex_indices_set((3 * index, 3 * index + 1, 3 * index + 2))
    for index in (4, 6, 11, 13):
        parent, local = waypoints[index]
        cable_guide(f"Cable keeper {index:02d}", group, parent, local, mats)
    return obj, anchors


def camera(name, group, position, target, lens):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    obj = bpy.data.objects.new(name, data)
    place(obj, group, location=position)
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    body = collection("01  Formline hardware")
    articulation = collection("02  Pose control and pivots")
    wiring = collection("03  Power cable")
    stage = collection("04  Studio and cameras")
    mats = {
        "base": material("Graphite | radially turned aluminum", (.093, .103, .112), .78, .37,
                         radial=True, anisotropy=.34),
        "charcoal": material("Graphite | ceramic bead blasted aluminum", (.041, .049, .057),
                             .62, .33, grain=.13, coat=.11),
        "gunmetal": material("Gunmetal | satin spacers", (.122, .135, .143), .76, .30,
                             grain=.08),
        "orange": material("Fired orange | satin anodized aluminum", (.63, .109, .024),
                           .59, .33, grain=.12, coat=.18),
        "steel": material("Pin caps | passivated stainless steel", (.35, .39, .41), .86, .28,
                          anisotropy=.31),
        "rubber": material("Black | molded elastomer", (.017, .020, .023), .05, .59, grain=.24),
        "cable": material("Power cable | woven black sleeve", (.033, .037, .038), .12, .54,
                          grain=.40),
        "engraving": material("Machining marks | oxidized metal", (.030, .034, .036), .55, .46),
        "legend": material("Laser marks | warm titanium", (.46, .43, .36), .48, .42),
        "opal": material("Diffuser | warm opal polymer", (.94, .66, .37), .05, .29,
                         grain=.06, emission=1.55),
        "led": material("Amber | standby indicator", (1, .25, .039), .02, .25, emission=2.5),
        "floor": material("Studio | smoked clay", (.111, .086, .071), .12, .49, grain=.07),
    }

    base = empty("Base datum", articulation)
    rig = empty("FORMLINE — Pose controls", articulation, base, (0, 0, .045), 1.05, "CIRCLE")
    rig.rotation_euler.x = pi / 2
    rig.show_in_front = True
    for name, (default, minimum, maximum, description) in POSE.items():
        rig[name] = default
        rig.id_properties_ui(name).update(min=minimum, max=maximum, soft_min=minimum,
                                           soft_max=maximum, description=f"{description} (degrees)")
    shoulder = empty("Shoulder pivot", articulation, base, (-.349, 0, .526))
    elbow = empty("Elbow pivot", articulation, shoulder, (0, 0, LOWER))
    wrist = empty("Wrist pivot", articulation, elbow, (0, 0, UPPER))
    for pivot, name in zip((shoulder, elbow, wrist), POSE):
        driver(pivot, rig, name)
    bpy.context.view_layer.update()

    cylinder("Base | molded grip pad", .867, .041, mats["rubber"], body, base, (0, 0, .025))
    cylinder("Base | weighted lower housing", .946, .158, mats["charcoal"],
             body, base, (0, 0, .119), bevel=.024)
    cylinder("Base | turned aluminum face", .931, .049, mats["base"],
             body, base, (0, 0, .204), bevel=.012)
    torus("Base | satin separation line", .928, .0033, mats["gunmetal"], body, base,
          (0, 0, .190))
    for i, radius in enumerate((.864, .879, .898), 1):
        torus(f"Base | concentric tool line {i}", radius, .00125, mats["engraving"],
              body, base, (0, 0, .228))
    cylinder("Switch | counterbore", .107, .006, mats["engraving"], body, base, (.506, -.241, .228))
    cylinder("Switch | satin cap", .084, .015, mats["gunmetal"], body, base, (.506, -.241, .236))
    torus("Switch | amber indicator ring", .065, .0028, mats["led"], body, base, (.506, -.241, .245))
    text_label("Base | maker's mark", "F O R M L I N E", .068, mats["legend"],
               body, base, (.276, -.582, .229))
    cylinder("Cable outlet | strain-relief gland", .054, .024, mats["rubber"],
             body, base, (-.695, .30, .232), bevel=.008)
    cylinder("Pedestal | foundation", .279, .064, mats["gunmetal"],
             body, base, (-.349, 0, .254), bevel=.015)
    for side in (-1, 1):
        y = side * .114
        box("Pedestal | yoke upright", (.237, .106, .249), mats["charcoal"],
            body, base, (-.349, y, .402), .031)
        cylinder("Pedestal | yoke crown", .118, .107, mats["charcoal"],
                 body, base, (-.349, y, .521), axis="Y", bevel=.012)

    for side in (-1, 1):
        label = "near" if side < 0 else "far"
        recessed_rail(f"Lower | {label} milled link", LOWER, side * RAIL_Y[0], .092,
                      mats["charcoal"], mats["rubber"], body, shoulder)
        recessed_rail(f"Upper | {label} milled link", UPPER, side * RAIL_Y[1], .080,
                      mats["orange"], mats["engraving"], body, elbow)
        cylinder(f"Elbow | {label} floating thrust washer", .107, .024, mats["gunmetal"],
                 body, shoulder, (0, side * .179, LOWER), axis="Y", bevel=.003)
        cylinder(f"Wrist | {label} thrust washer", .088, .018, mats["gunmetal"],
                 body, wrist, (0, side * .073, 0), axis="Y", bevel=.004)
    lower_axle = axle("Shoulder", body, shoulder, 0, .57, .291, mats)
    elbow_axle = axle("Elbow", body, shoulder, LOWER, .57, .291, mats, ring=mats["orange"])
    wrist_axle = axle("Wrist", body, elbow, UPPER, .329, .172, mats)
    cylinder("Elbow | inner steel core", .115, .153, mats["gunmetal"], body, elbow, axis="Y")
    for i, degrees in enumerate((-70, -50, -30, -10, 10, 30, 50, 70)):
        theta = radians(degrees)
        radius = .111
        mark = box(f"Elbow | index tick {i + 1}", (.012, .002, .009),
                   mats["legend"], body, shoulder,
                   (radius * sin(theta), -.3032, LOWER + radius * cos(theta)), .001)
        mark.rotation_euler.y = theta
    box("Upper link | witness mark", (.021, .002, .064), mats["legend"],
        body, elbow, (0, -.163, .225), .0015)

    box("Shade | wrist lug", (.408, .127, .137), mats["charcoal"], body, wrist,
        (.139, 0, .003), .044)
    shade_layer("Shade | cast heat sink", .525, 1.231, .345, .157, .017,
                mats["charcoal"], body, wrist, .023)
    shade_layer("Shade | orange edge reveal", .524, 1.232, .339, .016, -.069,
                mats["orange"], body, wrist, .005)
    shade_layer("Shade | lower optic surround", .524, 1.232, .326, .040, -.094,
                mats["gunmetal"], body, wrist, .010)
    diffuser = shade_layer("Shade | warm opal diffuser", .541, 1.216, .287, .029, -.114,
                           mats["opal"], body, wrist, .012)
    shade_layer("Shade | inset crown panel", .533, 1.218, .287, .016, .093,
                mats["base"], body, wrist, .007)
    for y in (-.108, -.072, -.036, 0, .036, .072, .108):
        box("Shade | cooling groove", (.209, .006, .002), mats["engraving"],
            body, wrist, (.55, y, .1014), .001)
    text_label("Shade | model engraving", "F O R M L I N E", .057, mats["legend"],
               body, wrist, (1.099, 0, .102))
    cable, anchors = build_cable(wiring, base, shoulder, elbow, wrist, mats)
    area("Shade | warm task beam", (1, .64, .31), 43, 1.16, body, (.88, 0, -.147),
         size_y=.48, parent=wrist)

    bpy.ops.mesh.primitive_plane_add(size=200)
    floor = bpy.context.object
    floor.name = "Seamless studio floor"
    place(floor, stage)
    finish(floor, mats["floor"], smooth=False)
    area("Key | broad overhead softbox", (1, .86, .70), 535, 4.6, stage,
         (1.1, -3.6, 6.0), (0, 0, 1.23), size_y=3.2)
    area("Fill | neutral front card", (.77, .85, 1), 157, 3.4, stage,
         (-4.6, -3.0, 3.1), (-.42, 0, 1.55), size_y=3.9)
    area("Rim | tall warm strip", (1, .67, .42), 575, 2.1, stage,
         (-2.0, 2.0, 4.1), (-.57, 0, 1.71), size_y=3.8)
    area("Edge | narrow reflection card", (.94, .95, 1), 117, .78, stage,
         (3.35, 1.2, 3.25), (.65, 0, 1.43), size_y=3.0)
    scene.world = bpy.data.worlds.new("Studio ambient")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (.38, .39, .42, 1)
    bg.inputs["Strength"].default_value = .21

    hero = camera("Hero | complete lamp", stage, (3.7, -7.3, 4.15), (.36, 0, 1.25), 63)
    detail = camera("Detail | elbow and cable sweep", stage, (1.21, -3.33, 3.06),
                    (-.928, .022, 2.31), 82)
    for frame, cam in ((1, hero), (2, detail)):
        marker = scene.timeline_markers.new(cam.name, frame=frame)
        marker.camera = cam
    scene.frame_end = 2
    scene.frame_set(1)
    scene.camera = hero
    return scene, rig, (shoulder, elbow, wrist), (lower_axle, elbow_axle, wrist_axle), diffuser, cable, anchors, hero, detail



VIEW_SETTINGS = {"hero": (1360, 1120, 1), "detail": (1280, 960, 2)}


def set_view(scene, camera_name):
    width, height, frame = VIEW_SETTINGS[camera_name]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.frame_set(frame)
    scene.render.filepath = f"//renders/{camera_name}.png"


def set_pose(scene, rig, angles):
    for name, value in zip(POSE, angles):
        rig[name] = value
    rig.update_tag()
    scene.frame_set(scene.frame_current)
    bpy.context.view_layer.update()
    return bpy.context.evaluated_depsgraph_get()


def world_center(obj, graph):
    return obj.evaluated_get(graph).matrix_world.translation


def box_corners(obj, graph):
    evaluated = obj.evaluated_get(graph)
    return [evaluated.matrix_world @ Vector(point) for point in evaluated.bound_box]


def validate(scene, rig, pivots, axles, diffuser, cable, anchors, hero, detail):
    from bpy_extras.object_utils import world_to_camera_view

    defaults = [limits[0] for limits in POSE.values()]
    extremes = [(limits[1], limits[2]) for limits in POSE.values()]
    assert pivots[1].parent == pivots[0] and pivots[2].parent == pivots[1]
    assert diffuser.parent == pivots[2]
    assert len(cable.modifiers) == len(anchors) == 19
    links = [obj for obj in bpy.data.objects if "milled link" in obj.name]
    assert len(links) == 4
    for obj in links:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        try:
            assert all(edge.is_manifold for edge in bm.edges), obj.name
            assert bm.calc_volume() > .005, obj.name
        finally:
            bm.free()

    set_view(scene, "hero")
    graph = set_pose(scene, rig, defaults)
    rest_tip = pivots[2].evaluated_get(graph).matrix_world @ Vector((1.5, 0, 0))
    tip_travel = 0
    for angles in (defaults, *product(*extremes)):
        graph = set_pose(scene, rig, angles)
        points = [world_center(pivot, graph) for pivot in pivots]
        for point, axle, pivot, angle in zip(points, axles, pivots, angles):
            assert (point - world_center(axle, graph)).length < 1e-5, axle.name
            evaluated = axle.evaluated_get(graph)
            axle_direction = (evaluated.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
            assert abs(axle_direction.dot(AXIS)) > .99999, axle.name
            assert abs(pivot.evaluated_get(graph).rotation_euler.y - radians(angle)) < 1e-5, pivot.name
        assert abs((points[1] - points[0]).length - LOWER) < 1e-5
        assert abs((points[2] - points[1]).length - UPPER) < 1e-5
        clearance = min(point.z for point in box_corners(diffuser, graph))
        assert clearance > .70, f"Diffuser clearance {clearance:.3f} at {angles}"
        tip = pivots[2].evaluated_get(graph).matrix_world @ Vector((1.5, 0, 0))
        tip_travel = max(tip_travel, (tip - rest_tip).length)

        evaluated = cable.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            assert len(mesh.vertices) > 1000
            points = [evaluated.matrix_world @ v.co for v in mesh.vertices]
            for anchor in anchors:
                center = world_center(anchor, graph)
                near = min((point - center).length_squared for point in points)
                assert near < .038 ** 2, f"Detached cable at {anchor.name} in {angles}"
        finally:
            evaluated.to_mesh_clear()
    assert tip_travel > .8

    graph = set_pose(scene, rig, defaults)
    product_meshes = [obj for obj in bpy.data.collections["01  Formline hardware"].objects
                      if obj.type == "MESH"]
    image_points = [world_to_camera_view(scene, hero, corner) for obj in product_meshes
                    for corner in box_corners(obj, graph)]
    assert all(.03 < p.x < .97 and .03 < p.y < .97 and p.z > 0 for p in image_points), (
        f"Hero bounds {min(p.x for p in image_points):.3f}–{max(p.x for p in image_points):.3f}, "
        f"{min(p.y for p in image_points):.3f}–{max(p.y for p in image_points):.3f}"
    )
    set_view(scene, "detail")
    joint_in_frame = world_to_camera_view(scene, detail, world_center(pivots[1], graph))
    assert .28 < joint_in_frame.x < .71 and .22 < joint_in_frame.y < .78
    set_view(scene, "hero")
    print("FORMLINE VALIDATED | four closed rails, three coaxial pins, nine poses, cable and framing",
          flush=True)


def set_render_settings(scene):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 36
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = .048
    scene.cycles.adaptive_min_samples = 12
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 4
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = .26


def prepare_editing(rig):
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_perspective = "CAMERA"
                space.shading.color_type = "MATERIAL"
                space.overlay.show_extras = False
            if area.type == "PROPERTIES":
                area.spaces.active.context = "OBJECT"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    render_options = parser.add_mutually_exclusive_group()
    render_options.add_argument("--build-only", action="store_true", help="Skip PNG rendering")
    render_options.add_argument("--view", choices=VIEW_SETTINGS, help="Render only the selected view")
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    scene, rig, pivots, axles, diffuser, cable, anchors, hero, detail = build_scene()
    set_render_settings(scene)
    validate(scene, rig, pivots, axles, diffuser, cable, anchors, hero, detail)
    prepare_editing(rig)
    bpy.context.preferences.filepaths.save_version = 0
    render_dir = ROOT / "renders"
    render_dir.mkdir(exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "formline.blend"))
    if arguments.build_only:
        return
    for view in (arguments.view,) if arguments.view else VIEW_SETTINGS:
        set_view(scene, view)
        scene.render.filepath = str(render_dir / f"{view}.png")
        print(f"FORMLINE RENDER | {view}", flush=True)
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
