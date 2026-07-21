# assets/

## `Base_Male.vrm`

A rigged, anime-proportioned humanoid base mesh (67-joint skeleton, standard VRM
bone naming, e.g. `J_Bip_C_Hips`, `J_Bip_L_UpperArm`) — the base mesh for a future
extension of `mannequin.py`: rendering depth/normal maps from an actual posed 3D
body instead of just an OpenPose line-skeleton, for stronger anatomy/volume
conditioning than joint lines alone can give (2026-07-20, requested after the
back-view mannequin work — see ARCHITECTURE.md §8b.8).

**Source:** [OpenGameArt.org — "VRoid Studio CC0 Models"](https://opengameart.org/content/vroid-studio-cc0-models),
`base_male.zip`. Originally released by VRoid (Pixiv) during VRoid Studio's alpha,
explicitly under CC0 — re-hosted on OpenGameArt.org as a direct download. **Not**
the same as VRoid Hub's `AvatarSample_A`/etc., which are explicitly *not* CC0
(checked and rejected before choosing this file — see the FAQ warning at
vroid.pixiv.help's "Do VRoid Studio's sample models come with conditions of use?").

**License:** CC0 (public domain equivalent) — no attribution legally required, but
the source is documented here for the honest record.

**Format:** VRM 0.x (binary glTF/.glb container with a VRM extension block).
Load with `pygltflib`'s `GLTF2().load_binary(...)` — NOT `.load()`, which
mis-sniffs this as text JSON and fails with a `UnicodeDecodeError` (found the hard
way; `pygltflib` was added to `requirements.txt` for this).

**Status:** downloaded and structurally verified only. The posing/depth-rendering
pipeline that actually uses this file is not yet built — see ARCHITECTURE.md §8b.8
and the project task list for the next steps (load skeleton, map VRM bone names to
`mannequin.py`'s existing joint/pose-preset convention, pose via bone rotations,
render a depth or normal map, wire into `workflow.py`'s ControlNet branch as an
additional/alternative conditioning to the current OpenPose line-skeleton map).
