# Prompt bổ sung cho model Tris 3D (gửi ChatGPT)

Companion đã chạy được `tris_mascot.glb` (chế độ **Tris 3D**): biểu cảm bằng shape key mắt,
mấp máy miệng theo giọng (`aa`), quay đầu/thân, vẫy tay, đổi màu LED theo cảm xúc.
Phần còn thiếu so với linh vật 2D là **hiệu ứng quanh đầu**. Code đã đọc sẵn các vật thể tên
`TRIS_FX_*` — chỉ cần model có chúng là tự hoạt động. Copy toàn bộ khối dưới đây gửi ChatGPT,
kèm file `tris_mascot.blend` và `build_tris.py` hiện tại.

---

```text
You are extending my existing Blender 5.2 character "Tris" (files: tris_mascot.blend, build_tris.py).
The model already works in my three.js web app. Add the items below WITHOUT changing anything that
already exists, then re-export and re-verify exactly like before (same build script workflow).

## Do NOT change (the web runtime depends on these)
- Every existing object name, the hierarchy, and every pivot:
  TRIS_Root > TRIS_BodyPivot (local y 0.34, glTF Y-up) > TRIS_HeadPivot (local y 0.28),
  TRIS_Arm_L / TRIS_Arm_R with their origins at the shoulders (local ±0.205, 0.18 under TRIS_BodyPivot),
  TRIS_HoverRing under TRIS_Root.
- TRIS_Eyes shape keys (names and order): blink, happy, love, sad, angry, surprised, curious, thinking,
  listening, sleepy, lookLeft, lookRight, lookUp, lookDown. TRIS_Mouth shape keys: aa, oh, smile, frown.
  All shape key values saved at 0.
- Material names (MAT_Tris_Shell, MAT_Tris_Visor, MAT_Tris_FaceLED, MAT_Tris_Accent, MAT_Tris_Emblem,
  MAT_Tris_Star, MAT_Tris_Hover) and the neutral LED emission color. Real-world scale (about 0.97 m tall).

## 1. Emotion FX objects (main task)
Create these objects, each parented to TRIS_HeadPivot, with EXACTLY these names:

| Object name          | Shown for emotion | Look                                                                 |
|----------------------|-------------------|----------------------------------------------------------------------|
| TRIS_FX_Heart        | love              | small puffy 3D heart, pink emission #FF8FB3, above the head, screen-right |
| TRIS_FX_Question     | curious           | bold "?" mark, light blue emission #A5B9FF, above the head, screen-right |
| TRIS_FX_Exclaim      | surprised         | bold "!" mark, white emission, above the head, screen-right          |
| TRIS_FX_Zzz          | sleepy            | three "Z" letters getting smaller upward, light blue emission        |
| TRIS_FX_Anger        | angry             | classic anime anger mark (four curved strokes), red emission #FF6B5E, upper corner of the head shell |
| TRIS_FX_Sparkles     | happy             | three small four-point stars around the head, gold emission #FFD36B  |
| TRIS_FX_Think        | thinking          | thought bubble (one oval + two small trailing circles) with three dots inside, white shell, blue dots |
| TRIS_FX_Listen       | listening         | two concentric arcs (sound waves) beside the character's right earpiece, blue emission |
| TRIS_FX_Tear_L       | sad               | small teardrop on the visor just below the left eye, blue emission #8FD3FF |
| TRIS_FX_Tear_R       | sad               | same, below the right eye                                             |

Rules for every FX object:
- One single object (join its parts), object origin at its own visual center, rotation 0, scale 1.
- Faces the front camera (the same direction the visor faces). Readable from the front at web size.
- At most 400 triangles each. Smooth shading. Emission strength 1 (no textures).
- Must not intersect the head shell, visor, ears or antenna; keep 3-5 mm clearance. Tears sit on the visor
  surface (0.5-1 mm in front of it) without z-fighting.
- Exported VISIBLE. The web app hides them by default and shows/animates them per emotion, so do NOT
  animate them, do NOT drive them with shape keys, and do NOT parent them under TRIS_Eyes or TRIS_Mouth.

## 2. Lighter arms
TRIS_Arm_L and TRIS_Arm_R currently have about 10,000 triangles each. Rebuild or decimate each to at most
3,000 triangles while keeping the same silhouette, one watertight component per arm, smooth shading, the same
material, and the SAME object origin at the shoulder. Total character triangles must be at most 30,000.

## 3. Optional (only if it does not risk the items above)
Append two mouth shape keys at the END of TRIS_Mouth's list: "ee" (wide, flat) and "ou" (small round).
Same rules as the existing mouth keys: projected onto the LED visor surface, default 0.

## Export
- tris_mascot.glb: glTF Binary, +Y up, apply modifiers, shape keys exported, custom node names kept,
  no animations, no cameras, no lights, character hierarchy only. Target size at most 1.5 MB.
- Save tris_mascot.blend in its neutral state (all shape keys 0, all FX visible).

## Verification (write evidence like the previous SELF_CHECKS.md)
1. Fresh-import the GLB into an empty scene and list every TRIS_FX_* object: exact name, parent
   (must be TRIS_HeadPivot), triangle count, world bounding box, and clearance to the head shell.
2. Confirm every pre-existing check still passes (names, pivots, shape keys and their order, materials).
3. Confirm arm triangle counts and the total triangle count.
4. Renders: an expression sheet where each emotion is shown with ONLY its FX object(s) visible, plus the
   front/three-quarter/side/back turnaround with all FX hidden.
Report any check you could not run instead of skipping it silently.
```

---

Sau khi ChatGPT gửi lại `tris_mascot.glb`: kéo thả file vào sân khấu Companion (hoặc ⚙ Tối ưu →
Chọn tệp). File được lưu trong trình duyệt và tự dùng ở chế độ Tris 3D. Muốn thay model mặc định
cho mọi trình duyệt thì chép đè vào `frontend/public/companion/models/tris_mascot.glb` và
`frontend/dist/companion/models/tris_mascot.glb`.
