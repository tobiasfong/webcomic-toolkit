"""
vrm_pose_depth.py — runs INSIDE Blender (headless, --background --python),
never directly by this project's own Python. Called via subprocess by
vrm_depth.py, which handles the Blender executable path, timeouts, and the
EXR-to-PNG conversion (Blender's own headless image-loading doesn't decode
pixel data in --background mode on this Blender version — verified live, not
assumed — so PNG conversion happens outside Blender entirely, in vrm_depth.py
using the OpenEXR package).

Imports a VRM humanoid mesh (assets/Base_Male.vrm by convention — a real
skinned/rigged mesh, not mannequin.py's line-skeleton), poses it standing with
arms at its sides (the VRM's own bind pose is a T-pose), places an orthographic
camera at the given yaw (0 = facing camera, 180 = back view — same convention
as mannequin.render_pose_map), and renders camera-space depth and normal
passes to EXR.

Requires the community VRM Add-on for Blender (saturday06/VRM-Addon-for-
Blender) already installed and enabled in this Blender's user preferences —
see vrm_depth.py's docstring for the one-time setup command.

Depth calibration (2026-07-22, see ARCHITECTURE.md §8b.9 for the full story):
the near/far window for the depth remap MUST be tight around the body's
actual ~0.25-unit front-to-back depth, not a generous guess — an oversized
window (the first attempt used +/-1.2, ~8x too wide) squeezes the body into a
tiny slice of the 0-1 output range, producing a nearly flat, low-contrast map
that looks like a clean silhouette but carries almost no relief information
for the ControlNet to use. This was the actual root cause of a hallucinated
duplicate head and other anatomy artifacts in early testing — not a
ControlNet-strength problem.

Usage (arguments after "--", positional):
    blender.exe --background --python vrm_pose_depth.py -- \\
        <vrm_path> <yaw_degrees> <out_depth.exr> <out_normal.exr> <width> <height>
"""

import sys, os, math
import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
VRM_PATH, YAW, OUT_DEPTH, OUT_NORMAL, W, H = argv
YAW = float(YAW)
W, H = int(W), int(H)

for name in ("Cube", "Camera", "Light"):
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.import_scene.vrm(filepath=VRM_PATH)
arm_obj = bpy.data.objects["Armature"]
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode="POSE")
pb = arm_obj.pose.bones


def rotate_bone(name, axis, degrees):
    b = pb[name]
    b.rotation_mode = "XYZ"
    rot = list(b.rotation_euler)
    idx = {"X": 0, "Y": 1, "Z": 2}[axis]
    rot[idx] += math.radians(degrees)
    b.rotation_euler = rot


# Only "standing" (arms down at sides) is implemented — the VRM's bind pose
# is a T-pose, rotated down via the upper-arm bones' local X axis (found by
# live trial: local Y is the bone's own long axis and has no visible effect;
# X is the axis that actually swings the arm down). Other presets
# (mannequin.py's t_pose/hands_behind_back/arms_crossed/walking) are NOT
# ported here yet — add more rotate_bone() calls per J_Bip_* joint if needed.
rotate_bone("J_Bip_L_UpperArm", "X", -85)
rotate_bone("J_Bip_R_UpperArm", "X", -85)
bpy.ops.object.mode_set(mode="OBJECT")

cam_data = bpy.data.cameras.new("Camera")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 2.0
cam_obj = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

dist = 3.0
th = math.radians(YAW)
cam_obj.location = (dist * math.sin(th), -dist * math.cos(th), 1.0)
direction = (0 - cam_obj.location[0], 0 - cam_obj.location[1], 1.0 - cam_obj.location[2])
cam_obj.rotation_euler = mathutils.Vector(direction).to_track_quat('-Z', 'Y').to_euler()

light_data = bpy.data.lights.new("Light", type="SUN")
light_obj = bpy.data.objects.new("Light", light_data)
bpy.context.collection.objects.link(light_obj)
light_obj.rotation_euler = (math.radians(45), 0, math.radians(45))

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x = W
scene.render.resolution_y = H

vl = bpy.context.view_layer
vl.use_pass_z = True
vl.use_pass_normal = True

# Blender 5.2 replaced Scene.node_tree/use_nodes with compositing_node_group,
# and CompositorNodeMapRange/CompositorNodeMath with the unified ShaderNode*
# equivalents (usable in any node-tree type) — verified live against this
# Blender version's actual API, not assumed from older docs.
tree = bpy.data.node_groups.new("Compositing", "CompositorNodeTree")
scene.compositing_node_group = tree
rl = tree.nodes.new("CompositorNodeRLayers")
rl.layer = vl.name

# Depth: map camera-space Z from [dist-0.25, dist+0.25] to [1.0 (near), 0.0
# (far)] -- near=bright/far=dark, the common SD depth-ControlNet convention.
map_range = tree.nodes.new("ShaderNodeMapRange")
map_range.inputs[1].default_value = dist - 0.25   # From Min
map_range.inputs[2].default_value = dist + 0.25   # From Max
map_range.inputs[3].default_value = 1.0           # To Min
map_range.inputs[4].default_value = 0.0           # To Max
map_range.clamp = True
tree.links.new(rl.outputs["Depth"], map_range.inputs[0])

# Normal: camera-space normal, each component [-1,1] -> [0,1] for RGB encode.
sep = tree.nodes.new("CompositorNodeSeparateColor")
tree.links.new(rl.outputs["Normal"], sep.inputs[0])
combine = tree.nodes.new("CompositorNodeCombineColor")
for channel in ("Red", "Green", "Blue"):
    m = tree.nodes.new("ShaderNodeMath")
    m.operation = "MULTIPLY_ADD"
    m.inputs[1].default_value = 0.5
    m.inputs[2].default_value = 0.5
    tree.links.new(sep.outputs[channel], m.inputs[0])
    tree.links.new(m.outputs["Value"], combine.inputs[channel])

# Write both remapped passes to EXR -- PNG conversion happens outside Blender
# (see module docstring for why: headless image-loading doesn't decode pixel
# data in --background mode on this Blender version).
tmp_depth_exr = os.path.splitext(OUT_DEPTH)[0] + "_raw.exr"
tmp_normal_exr = os.path.splitext(OUT_NORMAL)[0] + "_raw.exr"

depth_out = tree.nodes.new("CompositorNodeOutputFile")
depth_out.directory = os.path.dirname(tmp_depth_exr)
depth_out.file_output_items.new(socket_type="FLOAT", name="depth")
depth_out.file_name = os.path.splitext(os.path.basename(tmp_depth_exr))[0]
tree.links.new(map_range.outputs["Result"], depth_out.inputs["depth"])

normal_out = tree.nodes.new("CompositorNodeOutputFile")
normal_out.directory = os.path.dirname(tmp_normal_exr)
normal_out.file_output_items.new(socket_type="RGBA", name="normal")
normal_out.file_name = os.path.splitext(os.path.basename(tmp_normal_exr))[0]
tree.links.new(combine.outputs["Image"], normal_out.inputs["normal"])

bpy.ops.render.render(write_still=True)


def _resolve(base):
    # Blender's File Output node may or may not append a frame-number suffix
    # depending on version/settings -- check both rather than assume.
    frame = bpy.context.scene.frame_current
    with_suffix = f"{base[:-4]}{frame:04d}.exr"
    if os.path.isfile(base):
        return base
    if os.path.isfile(with_suffix):
        return with_suffix
    raise FileNotFoundError(f"Neither {base} nor {with_suffix} exists")


depth_exr_actual = _resolve(tmp_depth_exr)
normal_exr_actual = _resolve(tmp_normal_exr)

import shutil
shutil.move(depth_exr_actual, OUT_DEPTH)
shutil.move(normal_exr_actual, OUT_NORMAL)
print("DONE (raw EXR):", OUT_DEPTH, OUT_NORMAL)
