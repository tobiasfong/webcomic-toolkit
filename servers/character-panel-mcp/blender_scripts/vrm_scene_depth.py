"""
vrm_scene_depth.py — runs INSIDE Blender (headless, --background --python),
never directly by this project's own Python. Called via subprocess by
vrm_scene.py.

The multi-figure, arbitrarily-posed sibling of vrm_pose_depth.py. That script
renders ONE figure in ONE hardcoded standing pose at a given yaw, which covers
reference-sheet turnarounds. This one takes a JSON scene spec — any number of
VRM figures, each with its own world position, facing, and per-bone rotations —
so a two-character action beat can be posed and rendered as a single depth map.

Why this exists: flat lineart cannot express limb identity. A ControlNet line
map says "edge here", never "this outline is a leg and that one is a sleeve",
so where limbs cross, FLUX welds them — repeatedly rendering a kicking leg as a
continuation of a sleeve ending in a boot. Live-tested and ruled out: strength
sweeps 0.40-0.72, cleaned sketches, Kontext pose edits (0/7), and generating
each character separately (the failure persists with ONE figure in frame, which
is what proves it is limb identity and not limb overlap). Depth resolves it
because ordering is encoded per pixel — a leg at a different distance from a
sleeve is a different grey value no matter how their silhouettes cross.

Depth window is computed from the posed geometry rather than hardcoded.
vrm_pose_depth.py uses a hand-calibrated +/-0.25 around a single body, and its
docstring records why that tightness matters: an oversized window squeezes the
body into a sliver of the 0-1 range and yields a flat, near-useless map. That
constant cannot survive two figures at different distances, so here the range
is measured off the evaluated (posed, modifier-applied) mesh vertices in camera
space and padded slightly. Same principle — tight around the actual geometry —
applied automatically.

Scene spec (JSON, passed as a file path):

    {
      "width": 1024, "height": 1024,
      "camera": {"yaw": 0.0, "dist": 4.0, "ortho_scale": 3.0, "target_z": 1.0},
      "figures": [
        {"vrm": "assets/Base_Male.vrm",
         "location": [-0.6, 0.0, 0.0],
         "yaw": 20.0,
         "bones": {"J_Bip_R_UpperArm": {"X": -40, "Z": 25}}}
      ]
    }

`bones` maps VRM humanoid bone names (J_Bip_*) to per-axis degree offsets
applied to the bind pose (a T-pose), matching vrm_pose_depth.py's convention —
arms swing DOWN from T via the upper arm's local X. Axes are applied in XYZ
order on the bone's local euler.

Usage (arguments after "--", positional):
    blender.exe --background --python vrm_scene_depth.py -- \\
        <scene.json> <out_depth.exr>
"""

import sys, os, math, json
import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
SCENE_JSON, OUT_DEPTH = argv
spec = json.load(open(SCENE_JSON))

W = int(spec.get("width", 1024))
H = int(spec.get("height", 1024))
cam_spec = spec.get("camera", {})
YAW = float(cam_spec.get("yaw", 0.0))
DIST = float(cam_spec.get("dist", 4.0))
ORTHO = float(cam_spec.get("ortho_scale", 3.0))
TARGET_Z = float(cam_spec.get("target_z", 1.0))

for name in ("Cube", "Camera", "Light"):
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)


def import_figure(fig):
    """Import one VRM, pose its bones, and place it in the world.

    Each import creates a fresh 'Armature' object; Blender uniquifies the name
    (Armature.001, ...) so the newly-active object is tracked explicitly rather
    than looked up by name.
    """
    before = set(bpy.data.objects)
    bpy.ops.import_scene.vrm(filepath=fig["vrm"])
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    pb = arm.pose.bones
    for bone_name, axes in (fig.get("bones") or {}).items():
        if bone_name not in pb:
            print(f"WARNING: no bone {bone_name!r} on this rig, skipping")
            continue
        b = pb[bone_name]
        b.rotation_mode = "XYZ"
        rot = list(b.rotation_euler)
        for axis, deg in axes.items():
            rot[{"X": 0, "Y": 1, "Z": 2}[axis]] += math.radians(float(deg))
        b.rotation_euler = rot
    bpy.ops.object.mode_set(mode="OBJECT")

    arm.location = mathutils.Vector(fig.get("location", [0, 0, 0]))
    # The VRM importer leaves the armature in QUATERNION rotation mode, and
    # assigning rotation_euler on a quaternion-mode object is silently ignored
    # — location applies, facing does not. Switch modes before assigning.
    arm.rotation_mode = "XYZ"
    arm.rotation_euler = (0, 0, math.radians(float(fig.get("yaw", 0.0))))
    return arm


armatures = [import_figure(fig) for fig in spec["figures"]]

cam_data = bpy.data.cameras.new("Camera")
# Perspective by default, unlike vrm_pose_depth.py's ortho. Ortho is right for
# turnaround sheets — front and back views must scale-match — but an ortho
# projection has no foreshortening at all, so a limb thrust toward the viewer
# renders the same size as one held back. That leaves FLUX with no perspective
# cue and it improvises limb scale, which shows up as mismatched arms (live,
# 2026-07-28). Action panels want foreshortening; it is what sells the kick.
if str(cam_spec.get("type", "PERSP")).upper().startswith("ORTHO"):
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ORTHO
else:
    cam_data.type = "PERSP"
    cam_data.lens = float(cam_spec.get("lens", 50.0))
cam_obj = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

th = math.radians(YAW)
cam_obj.location = (DIST * math.sin(th), -DIST * math.cos(th), TARGET_Z)
direction = (-cam_obj.location[0], -cam_obj.location[1], TARGET_Z - cam_obj.location[2])
cam_obj.rotation_euler = mathutils.Vector(direction).to_track_quat("-Z", "Y").to_euler()

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x = W
scene.render.resolution_y = H

# Measure the real camera-space depth span of the posed geometry. bpy's
# matrix_world @ vertex gives world space; the camera's inverse matrix takes
# that to camera space, where -Z is distance in front of the lens.
depsgraph = bpy.context.evaluated_depsgraph_get()
cam_inv = cam_obj.matrix_world.inverted()
near, far = None, None
for obj in bpy.context.scene.objects:
    if obj.type != "MESH":
        continue
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    mw = ev.matrix_world
    for v in mesh.vertices:
        z = -(cam_inv @ (mw @ v.co)).z
        if near is None or z < near:
            near = z
        if far is None or z > far:
            far = z
    ev.to_mesh_clear()
if near is None:
    raise RuntimeError("no mesh geometry found — did the VRM import fail?")
pad = max(0.02, (far - near) * 0.05)
near, far = near - pad, far + pad
print(f"DEPTH WINDOW near={near:.4f} far={far:.4f} span={far - near:.4f}")

vl = bpy.context.view_layer
vl.use_pass_z = True

tree = bpy.data.node_groups.new("Compositing", "CompositorNodeTree")
scene.compositing_node_group = tree
rl = tree.nodes.new("CompositorNodeRLayers")
rl.layer = vl.name

# near -> 1.0 (bright), far -> 0.0 (dark): the standard SD depth-ControlNet
# convention, same as vrm_pose_depth.py.
map_range = tree.nodes.new("ShaderNodeMapRange")
map_range.inputs[1].default_value = near
map_range.inputs[2].default_value = far
map_range.inputs[3].default_value = 1.0
map_range.inputs[4].default_value = 0.0
map_range.clamp = True
tree.links.new(rl.outputs["Depth"], map_range.inputs[0])

tmp_exr = os.path.splitext(OUT_DEPTH)[0] + "_raw.exr"
depth_out = tree.nodes.new("CompositorNodeOutputFile")
depth_out.directory = os.path.dirname(tmp_exr)
depth_out.file_output_items.new(socket_type="FLOAT", name="depth")
depth_out.file_name = os.path.splitext(os.path.basename(tmp_exr))[0]
tree.links.new(map_range.outputs["Result"], depth_out.inputs["depth"])

# Hand cut-outs. FLUX draws hands well unprompted — it is the reason this
# project moved off SD1.5/SDXL — but Base_Male.vrm's hands are low-poly
# mittens, so conditioning on them actively makes hands WORSE than leaving
# them unconstrained. Rather than detect hands in the rendered image, project
# the hand bones we already know the 3D position of, and let vrm_scene.py
# paint those discs out of the depth map. Positions are emitted in normalized
# image coordinates (origin top-left) alongside a radius in the same units.
if spec.get("mask_hands", True):
    import bpy_extras.object_utils as bou
    cam_right = cam_obj.matrix_world.to_quaternion() @ mathutils.Vector((1.0, 0.0, 0.0))
    marks = []
    for arm in armatures:
        pb = arm.pose.bones
        for side in ("L", "R"):
            bone = f"J_Bip_{side}_Hand"
            if bone not in pb:
                continue
            wrist = arm.matrix_world @ pb[bone].head
            # hand length from a fingertip when the rig has finger bones,
            # otherwise a plausible constant — VRM rigs vary on this
            tip = None
            for cand in (f"J_Bip_{side}_Middle3", f"J_Bip_{side}_Middle2",
                         f"J_Bip_{side}_Index3"):
                if cand in pb:
                    tip = arm.matrix_world @ pb[cand].tail
                    break
            size = (tip - wrist).length if tip else 0.09
            centre = (wrist + tip) / 2.0 if tip else wrist
            c = bou.world_to_camera_view(scene, cam_obj, centre)
            e = bou.world_to_camera_view(scene, cam_obj, centre + cam_right * size)
            r = ((e.x - c.x) ** 2 + (e.y - c.y) ** 2) ** 0.5
            # world_to_camera_view's Y runs bottom-up; images run top-down
            marks.append({"x": c.x, "y": 1.0 - c.y, "r": r})
    with open(os.path.splitext(OUT_DEPTH)[0] + "_hands.json", "w") as f:
        json.dump(marks, f)
    print(f"HAND MARKS {len(marks)}")

bpy.ops.render.render(write_still=True)


def _resolve(base):
    # The File Output node may or may not append a frame-number suffix
    # depending on version/settings — check both rather than assume.
    frame = bpy.context.scene.frame_current
    with_suffix = f"{base[:-4]}{frame:04d}.exr"
    if os.path.isfile(base):
        return base
    if os.path.isfile(with_suffix):
        return with_suffix
    raise FileNotFoundError(f"Neither {base} nor {with_suffix} exists")


import shutil
shutil.move(_resolve(tmp_exr), OUT_DEPTH)
print("DONE (raw EXR):", OUT_DEPTH)
