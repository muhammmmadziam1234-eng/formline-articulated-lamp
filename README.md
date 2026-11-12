# Formline

A fictional precision desk lamp designed as an articulated study in graphite, fired-orange aluminum and warm opal light.

- **Hero** — the complete lamp in a warm architectural studio, with the shade and base read as one silhouette.
- **Detail** — the elbow stack, with its milled links, pin cap, thrust washers and power-cable sweep.
- **Editable assembly** — Formline’s meshes, procedural materials, pivots, lighting and two cameras are organized into named collections in formline.blend.

## Pose the lamp

Select **FORMLINE — Pose controls** in the Outliner. Open **Object Properties → Custom Properties** and edit the three values in degrees.

| Control | Default | Range | Reference |
| --- | ---: | ---: | --- |
| Shoulder tilt | −28° | −44° to −14° | Lower links from vertical |
| Elbow bend | 94° | 69° to 107° | Upper links relative to the lower links |
| Head pitch | −59° | −90° to −38° | Shade relative to the upper links |

The pivots share the hinge axes. The light source and diffuser follow the wrist. Frame 1 selects the hero camera and frame 2 selects the detail camera. The pose is static across both frames.

## Assembly decisions

The wider lower links straddle the upper pair at the elbow. A stainless pin spans the stack, and thrust washers occupy the gaps between the moving links. Each link has a closed, machined recess modeled into its mesh. The circular base uses a separate elastomer foot, weighted housing and radially turned deck.

A single Bezier cable runs from the base gland to the shade. Its anchors follow the corresponding joint frames. Keepers support its straight runs, while the bend at each hinge sits outside the pin caps. The opal diffuser and a separate warm area emitter provide the visible luminous surface and task-light pool.

The motion model represents the joint layout and pose range. Dimensions are Blender scene units for visualization.

## Rebuild

Use Blender 4.5.4 with its bundled Python. The source creates all geometry, text and materials procedurally.

```sh
blender --background --factory-startup --python build_formline.py
```

The script writes formline.blend, renders/hero.png (1360 × 1120) and renders/detail.png (1280 × 960) beside itself. Cycles uses CPU rendering, 36 maximum samples and denoising. Add -- --build-only to generate the editable file without rendering, or -- --view hero and -- --view detail for a single view.

Before saving, the script checks link topology, coaxial pins, fixed link lengths, diffuser clearance and cable attachment at the default pose and all eight combinations of angle limits. It also checks camera framing.
