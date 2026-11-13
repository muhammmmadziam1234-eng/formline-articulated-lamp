"""Build, measure and render the Formline articulation scene."""

from itertools import product
import json
from math import atan2, ceil, degrees

import bpy
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from mathutils.kdtree import KDTree


FPS = 15
LOOP_FRAME = 91
POSES = (
    (21, 27, "Raised", (-44.0, 69.0, -38.0)),
    (44, 50, "Forward", (-14.0, 97.0, -90.0)),
    (64, 70, "Lowered", (-21.0, 107.0, -48.0)),
)
SEQUENCE = (
    (1, "default"), (14, "raising"), (21, "raised"), (35, "reaching"),
    (44, "forward"), (57, "lowering"), (64, "lowered"), (77, "returning"),
)
X_AXIS = Vector((1, 0, 0))
Y_AXIS = Vector((0, 1, 0))
Z_AXIS = Vector((0, 0, 1))


def corners(obj):
    return [obj.matrix_world @ Vector(point) for point in obj.bound_box]


def measure(graph, pivots, axles, diffuser, datum, base, expected, lengths):
    shoulder, elbow, wrist = [pivot.evaluated_get(graph) for pivot in pivots]
    centers = [pivot.matrix_world.translation for pivot in (shoulder, elbow, wrist)]
    angles = [degrees(pivot.rotation_euler.y) for pivot in (shoulder, elbow, wrist)]
    assert all(abs(actual - target) < 1e-4 for actual, target in zip(angles, expected)), (
        angles, expected
    )
    for center, axle in zip(centers, axles):
        shaft = axle.evaluated_get(graph).matrix_world
        assert (shaft.translation - center).length < 1e-5, axle.name
        assert abs((shaft.to_3x3() @ Z_AXIS).normalized().dot(Y_AXIS)) > .99999, axle.name
    for start, end, length in zip(centers, centers[1:], lengths):
        assert abs((end - start).length - length) < 1e-5

    point = datum.evaluated_get(graph).matrix_world.translation
    origin = base.evaluated_get(graph).matrix_world.translation
    shade_axis = wrist.matrix_world.to_3x3() @ X_AXIS
    clearance = min(corner.z for corner in corners(diffuser.evaluated_get(graph)))
    assert clearance > .70, (angles, clearance)
    assert abs((point - origin).y) < 1e-5
    return {
        "forward_reach_bu": (point - origin).x,
        "height_bu": point.z,
        "shade_pitch_deg": degrees(atan2(shade_axis.z, shade_axis.x)),
        "diffuser_box_floor_clearance_bu": clearance,
    }


def check_cable(graph, cable, anchors):
    evaluated = cable.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    try:
        assert len(mesh.vertices) > 1000
        tree = KDTree(len(mesh.vertices))
        for vertex in mesh.vertices:
            tree.insert(evaluated.matrix_world @ vertex.co, vertex.index)
        tree.balance()
        offsets = [tree.find(anchor.evaluated_get(graph).matrix_world.translation)[2]
                   for anchor in anchors]
        assert max(offsets) < .038, anchors[offsets.index(max(offsets))].name
        return max(offsets)
    finally:
        evaluated.to_mesh_clear()


def joint_grid(minimum, maximum):
    intervals = ceil((maximum - minimum) / 5)
    return [minimum + (maximum - minimum) * index / intervals
            for index in range(intervals + 1)]


def add_keys(scene, rig, names, defaults):
    keys = [(1, "Default", defaults), (7, None, defaults)]
    for frame, hold, label, angles in POSES:
        keys.extend(((frame, label, angles), (hold, None, angles)))
    keys.extend(((84, "Return", defaults), (LOOP_FRAME, None, defaults)))
    for frame, label, angles in keys:
        if label:
            scene.timeline_markers.new(label, frame=frame)
        for name, angle in zip(names, angles):
            rig[name] = angle
            rig.keyframe_insert(data_path=f'["{name}"]', frame=frame, group="Joint angles")

    animation = rig.animation_data
    animation.action.name = "Formline | articulation loop"
    curves = action_get_channelbag_for_slot(animation.action, animation.action_slot).fcurves
    assert len(curves) == len(names)
    for curve in curves:
        for key in curve.keyframe_points:
            key.interpolation = "BEZIER"
            key.handle_left_type = key.handle_right_type = "AUTO_CLAMPED"
    return keys


def build(studio, studio_rig, pivots, axles, diffuser, cable, anchors, controls, make_camera):
    bpy.ops.scene.new(type="FULL_COPY")
    scene = bpy.context.scene
    assert scene != studio
    scene.name = "Articulation study"
    scene.timeline_markers.clear()
    scene.frame_start = 1
    scene.frame_end = LOOP_FRAME - 1
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.render.resolution_x = 640
    scene.render.resolution_y = 520
    configure_video(scene, "//renders/articulation-full.mp4")
    scene.cycles.samples = 12
    scene.cycles.adaptive_min_samples = 6
    scene.render.use_persistent_data = True

    def copied(obj):
        duplicate = scene.objects[f"{obj.name}.001"]
        assert duplicate != obj
        return duplicate

    rig = copied(studio_rig)
    rig.name = "FORMLINE — Motion controls"
    pivots = [copied(pivot) for pivot in pivots]
    axles = [copied(axle) for axle in axles]
    diffuser = copied(diffuser)
    cable = copied(cable)
    anchors = [copied(anchor) for anchor in anchors]
    base = rig.parent
    assert diffuser.parent == scene.objects["Shade | warm task beam.001"].parent == pivots[2]
    assert all(modifier.object == anchor for modifier, anchor in zip(cable.modifiers, anchors))
    assert len(cable.modifiers) == len(anchors) == 19
    lengths = [pivots[1].location.length, pivots[2].location.length]

    study_camera = make_camera("Study | locked articulation view", scene.collection,
                               (2.25, -10, 3.45), (.12, 0, 1.86), 65)
    study_camera.data.type = "ORTHO"
    study_camera.data.ortho_scale = 8.20
    scene.camera = study_camera
    datum = bpy.data.objects.new("Diffuser center | measurement datum", None)
    scene.collection.objects.link(datum)
    datum.parent = diffuser
    datum.location = sum((Vector(corner) for corner in diffuser.bound_box), Vector()) / 8
    datum.empty_display_size = .06

    def evaluate(expected):
        graph = bpy.context.evaluated_depsgraph_get()
        return graph, measure(graph, pivots, axles, diffuser, datum, base, expected, lengths)

    names = tuple(controls)
    defaults, minimums, maximums = zip(*(values[:3] for values in controls.values()))
    grid = [joint_grid(low, high) for low, high in zip(minimums, maximums)]
    sampled = []
    for requested, expected in (
        (tuple(angle - 10 for angle in minimums), minimums),
        (tuple(angle + 10 for angle in maximums), maximums),
        *((angles, angles) for angles in product(*grid)),
    ):
        for name, angle in zip(names, requested):
            rig[name] = angle
        rig.update_tag()
        bpy.context.view_layer.update()
        _, measurement = evaluate(expected)
        if requested == expected:
            sampled.append(measurement)

    keys = add_keys(scene, rig, names, defaults)
    keyed = {frame: (label, angles) for frame, label, angles in keys if label}
    hardware = [obj for group in (diffuser.users_collection[0], cable.users_collection[0])
                for obj in group.objects if obj.type in {"MESH", "FONT", "CURVE"}]
    framing = 1.0
    cable_offset = 0.0
    poses = []
    for frame in range(1, LOOP_FRAME + 1):
        scene.frame_set(frame)
        angles = tuple(rig[name] for name in names)
        assert all(low - 1e-5 <= angle <= high + 1e-5
                   for angle, low, high in zip(angles, minimums, maximums)), (frame, angles)
        graph, measurement = evaluate(angles)
        cable_offset = max(cable_offset, check_cable(graph, cable, anchors))
        for obj in hardware:
            for corner in corners(obj.evaluated_get(graph)):
                p = world_to_camera_view(scene, study_camera, corner)
                assert p.z > 0
                framing = min(framing, p.x, 1 - p.x, p.y, 1 - p.y)
        if frame in keyed:
            label, expected = keyed[frame]
            assert all(abs(angle - target) < 1e-5 for angle, target in zip(angles, expected))
            poses.append({"frame": frame, "pose": label, "joint_angles_deg": list(expected),
                          **measurement})
        if frame == LOOP_FRAME:
            assert all(abs(angle - target) < 1e-5 for angle, target in zip(angles, defaults))
            assert all(abs(measurement[name] - poses[0][name]) < 1e-5 for name in measurement)
    assert framing > .04, f"Study framing margin {framing:.3f}"
    scene.frame_set(1)
    return scene, rig, {
        "datum": "Center of the opal diffuser's local bounding box",
        "axes": {"forward_reach_bu": "Signed +X from base center",
                 "height_bu": "+Z from the studio floor",
                 "shade_pitch_deg": "Shade axis from +X toward +Z, positive nose-up"},
        "joint_order": list(names),
        "grid_points_per_joint": [len(axis) for axis in grid],
        "grid_pose_count": len(sampled),
        "sampled_ranges": {name: [min(sample[name] for sample in sampled),
                                  max(sample[name] for sample in sampled)] for name in sampled[0]},
        "motion": {"fps": FPS, "playback_frames": [1, scene.frame_end],
                   "verified_frames_including_loop_key": LOOP_FRAME,
                   "rendered_sequence_frames": [frame for frame, _ in SEQUENCE],
                   "minimum_normalized_camera_margin": framing,
                   "maximum_cable_anchor_to_surface_bu": cable_offset,
                   "poses": poses},
    }


def write_evidence(evidence, path):
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"FORMLINE STUDY VERIFIED | {evidence['grid_pose_count']} grid poses, "
          f"{LOOP_FRAME} animation frames, all 19 cable anchors per frame", flush=True)


def configure_video(scene, path):
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.use_file_extension = False
    scene.render.filepath = path


def render(scene, folder):
    sequence_dir = folder / "motion"
    sequence_dir.mkdir(exist_ok=True)
    scene.render.image_settings.file_format = "PNG"
    plates = []
    for index, (frame, name) in enumerate(SEQUENCE, 1):
        path = sequence_dir / f"{index:02d}-{name}.png"
        scene.frame_set(frame)
        scene.render.filepath = str(path)
        print(f"FORMLINE RENDER | sequence plate {index}: frame {frame}", flush=True)
        bpy.ops.render.render(write_still=True)
        plates.append((frame, path))

    preview = bpy.data.scenes.new("Sequence encoding")
    bpy.context.window.scene = preview
    preview.render.threads_mode = "FIXED"
    preview.render.threads = 3
    preview.render.resolution_x = scene.render.resolution_x
    preview.render.resolution_y = scene.render.resolution_y
    preview.render.fps = FPS
    preview.frame_start = 1
    preview.frame_end = LOOP_FRAME - 1
    preview.view_settings.view_transform = "Standard"
    preview.sequencer_colorspace_settings.name = "sRGB"
    editor = preview.sequence_editor_create()
    for index, (frame, path) in enumerate(plates):
        end = plates[index + 1][0] if index + 1 < len(plates) else 84
        strip = editor.strips.new_image(path.stem, str(path), 1, frame)
        strip.frame_final_duration = end - frame
    strip = editor.strips.new_image("Return to default", str(plates[0][1]), 1, 84)
    strip.frame_final_duration = LOOP_FRAME - 84
    temporary = folder / "articulation-preview.pending.mp4"
    configure_video(preview, str(temporary))
    bpy.ops.render.render(animation=True)
    temporary.replace(folder / "articulation-preview.mp4")
