# Prompt dựng linh vật Tris trong Blender

Bộ prompt để đưa cho AI làm việc với Blender: Blender MCP, Claude/ChatGPT viết script
`bpy`, hoặc addon AI trong Blender. Prompt viết bằng tiếng Anh vì AI tạo code `bpy` chính
xác hơn với tiếng Anh. Mọi con số, tên object và tên shape key khớp với hệ cảm xúc của
Companion (`frontend/public/companion/index.html`).

Mục tiêu: robot linh vật **nguyên bản** (không sao chép EVE của WALL-E), có màn hình mặt
LED với **14 shape key cho mắt** và **4 shape key cho miệng**, có pivot để code
three.js lắc đầu, vẫy tay, nhún người; xuất GLB.

## Cách dùng

| Cách | Làm thế nào |
|---|---|
| **A. AI điều khiển Blender** (Blender MCP…) | Dán **Master prompt** một lần, hoặc dán `SPEC` rồi từng **Step 1→10** để AI làm và kiểm tra từng phần. |
| **B. Nhờ LLM viết script** | Dán Master prompt vào Claude/ChatGPT → nhận một file `.py` → Blender: tab **Scripting** → **New** → dán → **Run Script** (Alt+P). Lỗi thì dùng **Prompt sửa lỗi** ở cuối. |
| **C. Tự dựng tay** | Dùng phần `SPEC` như bản vẽ kỹ thuật: mọi kích thước, vị trí, màu đều có số. |

Cần Blender **x64** cho máy Intel. Bản `windows.arm64` không chạy trên i7-8750H.
Bản ổn định hiện tại là 5.2.2 LTS: `winget install BlenderFoundation.Blender`.

---

## Master prompt (một lần dán)

```text
You are an expert Blender 5.2 technical artist and Python (bpy) developer. Build an ORIGINAL, cute robot mascot named "Tris" for a local English-tutor app, entirely procedurally with the Blender Python API, ready to export as a GLB for a three.js web companion. Follow the specification below EXACTLY (names, units, numbers). Work in stages and after every stage print a short report (objects created, vertex counts, checks passed).

## 0. Global rules
- Blender 5.2 (x64). Units: metric, 1 unit = 1 m. Z is up. The character FACES −Y (Front view, Numpad 1, shows the face). The character's LEFT is +X; suffix "_L" = +X, "_R" = −X. Never use ".L"/".R" in names: three.js strips dots from node names on load.
- Total height ≈ 1.03 m from the ground (z = 0) to the antenna-star tip.
- Write ONE idempotent script. On start, delete only objects whose names start with "TRIS_", materials starting with "MAT_Tris_", and the orphan meshes they used. Never touch the user's other objects.
- Build geometry with bmesh / mesh.from_pydata; avoid fragile bpy.ops calls that depend on UI context. Every mesh object must end with rotation (0,0,0) and scale (1,1,1): bake transforms into vertex data. Object origins are given below.
- Smooth shading via polygon.use_smooth = True (mesh.use_auto_smooth no longer exists). Subdivision Surface modifiers use viewport level = render level = 1 unless stated.
- Principled BSDF socket names (Blender 4.0+): "Base Color", "Metallic", "Roughness", "Coat Weight", "Coat Roughness", "Emission Color", "Emission Strength". Colours below are sRGB hex: convert to linear before assigning (c <= 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4), alpha 1.
- Do NOT access action.fcurves (the legacy Action API was removed in 5.x); only use keyframe_insert(). The EEVEE engine id is 'BLENDER_EEVEE'. Do not use material.blend_method or EEVEE bloom settings.
- Meshes that carry shape keys (TRIS_Eyes, TRIS_Mouth) must have NO modifiers.
- Keep the design original — NOT EVE from WALL-E: no blade/leaf-shaped arms, no body that is widest at the top and tapers to a point. Tris's signature: bottom-heavy gumdrop body, wide mochi-shaped head, star antenna, headphone ear discs, mitten hands, chest star emblem, hover ring.

## 1. Body — TRIS_Body (origin (0,0,0.34))
- Ellipsoid semi-axes X 0.19, Y 0.17, Z 0.24 centred at (0,0,0.34) → bottom z 0.10 (it hovers), top z 0.58.
- Bottom-heavy taper: for every vertex with local z > 0 multiply x and y by (1 − 0.18·t), where t = local_z / 0.24.
- Base mesh: UV sphere 32 segments × 24 rings; Subdivision 1; smooth; MAT_Tris_Shell.

## 2. Head — TRIS_Head (origin (0,0,0.76))
- Pure ellipsoid (keep it exact, the face is projected onto it): semi-axes X 0.20, Y 0.17, Z 0.155, centre (0,0,0.76) → bottom 0.605 (25 mm gap above the body), top 0.915.
- UV sphere 48 × 32; Subdivision 1; smooth; MAT_Tris_Shell.

## 3. Face screen — TRIS_Visor (origin (0,0,0.76))
- A patch of a slightly larger ellipsoid with the same centre: Xv 0.2016, Yv 0.17136, Zv 0.15624 (head × 1.008).
- Domain in head-local (x, z): ellipse centred at z = −0.010, half-width 0.160, half-height 0.112.
- Polar grid: 1 centre vertex + 20 rings × 64 segments. For ring r in (0,1] and angle θ: x = 0.160·r·cosθ, z = −0.010 + 0.112·r·sinθ, y = −Yv·sqrt(1 − (x/Xv)² − (z/Zv)²). Triangle fan for ring 1, quads outward. All face normals point toward −Y.
- No subdivision; MAT_Tris_Visor.
- TRIS_VisorRim: a closed tube following the visor boundary (r = 1), tube radius 0.004, 64 segments along the loop × 8 around the tube, pushed 1 mm outward along the surface normal; MAT_Tris_Shell. Build it as a mesh, not a curve object.

## 4. LED eyes — TRIS_Eyes (origin (0,0,0.76)) — the expression system
One mesh object with two islands (eye at +X, eye at −X). NO modifiers. Material MAT_Tris_FaceLED.
Topology per eye ("grid"): 33 columns × 8 rows = 264 vertices and 224 quads; 528 vertices in total. Column j (0..32) sits at u_j = −aw·cos(π·j/32), ordered from −X to +X. Row k (0..7) sits at z = bottom(u) + (top(u) − bottom(u))·k/7. Quad (k, j) = (v[k][j], v[k][j+1], v[k+1][j+1], v[k+1][j]) so normals face −Y. Vertex ORDER (eye +X then −X → row bottom→top → column −X→+X) is identical in the Basis and in every shape key.
Why 8 rows: a quad spanning the whole eye height would sag up to 7 mm behind the curved visor (hollow eyes). With 8 rows the chord sag stays below 0.3 mm. Do NOT flatten columns to one depth either: that makes the eyes float 10–20 mm off the face.
Placement: eye centres in head-local (x, z) = (±0.072, +0.005). EVERY vertex (x, z) is projected onto the LED-layer ellipsoid Xe 0.2032, Ye 0.17272, Ze 0.15748 (head × 1.016): y = −Ye·sqrt(1 − (x/Xe)² − (z/Ze)²).
Notation: a = 0.030, b = 0.0425; s = +1 for the +X eye, −1 for the −X eye; outer = s·u; ell(u,aw,bh) = bh·sqrt(max(0, 1 − (u/aw)²)); sup(u,aw,h,n) = h·(1 − |u/aw|^n)^(1/n); dx/dz are offsets added to the eye centre.
Shapes as top(u) / bottom(u):
- Basis (neutral): aw = a; top = ell(u,a,b); bottom = −top.
- blink: aw = 1.08a; top = ell(u,aw,0.12b); bottom = −top; dz = −0.006.
- happy (∩ smiling arcs): Ro = 0.0336, Ri = 0.55·Ro, c = −0.015, aw = Ro; top = c + 0.95·sqrt(Ro² − u²); bottom = c + 0.95·sqrt(max(0, Ri² − u²)).
- love (hearts): outline x = 16sin³t, y = 13cos t − 5cos2t − 2cos3t − cos4t, scaled by k = 0.035/16 and shifted up by 2.5k; aw = 0.035; top/bottom = max/min y where the outline crosses the vertical line at u (clamp |u| ≤ 0.999·aw).
- sad: aw = a, bh = 0.85b, dz = −0.006; L = 0.45bh − 0.55bh·(outer/aw); bottom = −ell(u,aw,bh); top = max(bottom, min(ell(u,aw,bh), L)) (outer corners droop).
- angry: aw = a, bh = 0.90b, dz = −0.004; L = 0.40bh + 0.60bh·(outer/aw); same clamp as sad (inner corners pressed down).
- surprised: aw = 0.040; top = ell(u,0.040,0.045); bottom = −top; dz = +0.004.
- curious: +X eye scaled ×1.18 (aw 1.18a, bh 1.18b, dz +0.003); −X eye ×0.82 (aw 0.82a, bh 0.82b, dz −0.003).
- thinking: both eyes a rounded dash glancing up toward −X (NOT mirrored): aw = 0.95a; top = sup(u,aw,0.30b,8); bottom = −top; dx = −0.012; dz = +0.016.
- listening: aw = 1.08a, bh = 1.08b, dz = +0.003.
- sleepy: aw = 1.05a; centre line z = −0.008; half-thickness sup(u,aw,0.0045,4).
- lookLeft: Basis shifted dx = +0.022; lookRight: dx = −0.022; lookUp: dz = +0.016; lookDown: dz = −0.016.
Shape-key names exactly: blink, happy, love, sad, angry, surprised, curious, thinking, listening, sleepy, lookLeft, lookRight, lookUp, lookDown (slider 0–1, relative to Basis).

## 5. LED mouth — TRIS_Mouth (origin (0,0,0.76))
Same grid method with 17 columns × 3 rows = 51 vertices, centre (0, −0.068), same LED layer, every vertex projected, NO modifiers, MAT_Tris_FaceLED.
- Basis: rounded bar aw = 0.016, half-thickness sup(u,aw,0.0028,4).
- aa: ellipse aw 0.014, bh 0.011. oh: ellipse aw 0.010, bh 0.010.
- smile: aw 0.020, centre line −0.004 + 0.008·(u/aw)², half-thickness sup(u,aw,0.0028,4). frown: same with centre line +0.004 − 0.008·(u/aw)².
Shape-key names: aa, oh, smile, frown.

## 6. Accessories
- TRIS_Ear_L / TRIS_Ear_R: cylinder radius 0.062, depth 0.034, axis X, centres (±0.212, 0.005, 0.765); Bevel modifier width 0.006, 3 segments; MAT_Tris_Shell.
- TRIS_EarRing_L / _R: torus major radius 0.050, minor 0.008, axis X, at x = ±0.234, y 0.005, z 0.765 (must stand clearly proud of the ear disc so it reads from the front); MAT_Tris_Accent.
- TRIS_AntennaStalk: cylinder radius 0.0055 from z 0.905 to z 0.995 (its top ends hidden inside the star); MAT_Tris_Shell.
- TRIS_AntennaStar: 5-point star in the XZ plane facing −Y, one point straight up, outer radius 0.032, inner 0.014, thickness 0.014 along Y, Bevel 0.003 × 2 segments, centre (0,0,0.995); MAT_Tris_Star.
- TRIS_Arm_L / _R (mitten hands): ellipsoid (0.050, 0.045, 0.110) plus a thumb-nub ellipsoid (0.022, 0.020, 0.032), thumb on the front-inner side at 60 % of the mitten length. Fuse them into ONE closed surface (Boolean Union, then Voxel Remesh 0.004 and Subdivision 1) so there is no crease where the thumb meets the mitten. Object ORIGIN = shoulder pivot (±0.205, 0, 0.52). The mitten hangs below it (centre at local (0,0,−0.10)) and is tilted so the hand tip swings 12° outward, away from the body; bake the tilt into the vertices. MAT_Tris_Shell.
- TRIS_Emblem: 5-point star, outer 0.045, inner 0.019, thickness 0.005, on the body front at z = 0.42, oriented to the body surface normal. Seat it on the EVALUATED (subdivided) body, not the analytic ellipsoid: subdivision shrinks the body ~1.4 mm there. The back face must sit ~0.5 mm inside the body and the front face 2–4 mm proud. Ray-cast or use a BVH to check. Material MAT_Tris_Emblem.
- TRIS_HoverRing: horizontal torus major radius 0.11, minor 0.010 at z 0.065; MAT_Tris_Hover.

## 7. Materials (Principled BSDF, Metallic 0 everywhere)
- MAT_Tris_Shell: Base #F4F5F8, Roughness 0.25, Coat Weight 0.5, Coat Roughness 0.06.
- MAT_Tris_Visor: Base #050608, Roughness 0.08, Coat Weight 1.0, Coat Roughness 0.02.
- MAT_Tris_FaceLED: Base #000000, Roughness 1.0, Emission Color #CDD9FF, Emission Strength 1.0 (the rendered pixel then equals the hex; strengths above 1 wash every emotion colour out to white).
- MAT_Tris_Accent: Base #A5B9FF, Roughness 0.35, Emission #A5B9FF, Strength 1.0.
- MAT_Tris_Emblem: Base #FFE08A, Roughness 0.35, Emission #FFE08A, Strength 1.0 (echoes the antenna star and reads on the white body).
- MAT_Tris_Star: Base #FFE08A, Roughness 0.35, Emission #FFE08A, Strength 1.0.
- MAT_Tris_Hover: Base #A5B9FF, Roughness 0.50, Emission #A5B9FF, Strength 1.0.
For a glow, use the compositor Glare node in previews, or bloom in three.js. Do not raise the strength.

## 8. Hierarchy (pivots for the runtime)
TRIS_Root (Empty at (0,0,0))
├─ TRIS_HoverRing
└─ TRIS_BodyPivot (Empty at (0,0,0.34))
   ├─ TRIS_Body, TRIS_Emblem, TRIS_Arm_L, TRIS_Arm_R
   └─ TRIS_HeadPivot (Empty at (0,0,0.62), the "neck")
      └─ TRIS_Head, TRIS_Visor, TRIS_VisorRim, TRIS_Eyes, TRIS_Mouth, TRIS_Ear_L, TRIS_Ear_R, TRIS_EarRing_L, TRIS_EarRing_R, TRIS_AntennaStalk, TRIS_AntennaStar
Empties have zero rotation and unit scale. Parent with an IDENTITY matrix_parent_inverse and set each child's location = its world origin − the parent's world origin, so world positions stay exactly as specified.

## 9. Preview scene (named TRIS_* so it is rebuilt with everything else)
- TRIS_Cam at (0, −2.6, 0.62) with a Track To constraint on an empty TRIS_CamTarget at (0,0,0.56); focal length 50 mm; set as the scene camera.
- Area lights aimed at (0,0,0.55): TRIS_Key 400 W, size 1.5, at (−1.6, −1.8, 1.8); TRIS_Fill 150 W at (1.8, −1.2, 1.0); TRIS_Rim 300 W at (0.5, 1.8, 1.6).
- World colour #12141C, strength 0.6. Engine EEVEE, resolution 1024 × 1024. Colour Management: View Transform 'Standard', Look None, Exposure 0, Gamma 1 (AgX desaturates the LED colours). Keep a small specular highlight on the key light (specular 0.6) so the visor still reads as glass.
- If RENDER_PREVIEWS is True: for each eye shape key set it to 1 (all others 0), set the LED colour (Base + Emission of MAT_Tris_FaceLED) from the emotion table and render to //renders/tris_<name>.png. Emotion colours: neutral #CDD9FF, happy #FFE08A, love #FFB3CF, sad #7F93C9, angry #FF9D97, surprised #FFFFFF, curious #CDD9FF, thinking #CDD9FF, listening #A5B9FF, sleepy #7F93C9; blink and look* keys use #CDD9FF. Also render a "talking" frame (mouth key aa = 1) and a turnaround (front, ¾, side, back) with Film Transparent on. Afterwards reset every key to 0 and the LED colour to #CDD9FF.

## 10. Optional animation clips (MAKE_ANIMATIONS, default False)
24 fps, loopable (first key = last key), keyframe_insert only. Push each clip to an NLA track named exactly like the clip on every object it animates, then clear the active action. Do not mute tracks.
- Idle (frames 1–97): TRIS_BodyPivot z 0 → +0.012 → 0 (sine); TRIS_HeadPivot rotation X ±2° and Y ±3° (out of phase); arms rotate around Y ±5° alternately; TRIS_HoverRing scale 1 → 1.06 → 1.
- Wave (1–49): TRIS_Arm_R lifts outward about 110° around Y, wiggles ±15° three times, returns.
- Hop (1–25): TRIS_BodyPivot z up 0.06 and back, ease-in/out.
- Blink (1–9): TRIS_Eyes shape key blink 0 → 1 → 0.

## 11. Export
- Save the file as //tris_mascot.blend (only if the file has been saved before; otherwise skip and report).
- BEFORE exporting, set every shape key value on TRIS_Eyes and TRIS_Mouth to 0 and the LED colour to #CDD9FF. Blender 5.x creates new shape keys at value 1.0, and the exporter writes those values as the default morph weights; three.js would then load the model with all 14 expressions applied at once.
- Select TRIS_Root and all of its descendants, then:
  bpy.ops.export_scene.gltf(filepath=EXPORT_PATH, export_format='GLB', use_selection=True, export_apply=True, export_yup=True, export_morph=True, export_morph_normal=False, export_cameras=False, export_lights=False, export_animations=MAKE_ANIMATIONS, export_animation_mode='NLA_TRACKS')
  Default EXPORT_PATH = //tris_mascot.glb. If a keyword is rejected (TypeError), retry without that keyword and report it.
- Budget: ≤ 50 000 triangles after modifiers, GLB ≤ 5 MB, no image textures.

## 12. Self-checks (print PASS/FAIL for each)
- TRIS_Eyes: 528 vertices, Basis + 14 shape keys with the exact names. TRIS_Mouth: 51 vertices, Basis + 4 shape keys.
- Face normals of TRIS_Eyes, TRIS_Mouth and TRIS_Visor point toward −Y, for the Basis AND for every key's coordinates.
- With every eye key at 1, one at a time, no eye vertex leaves the visor domain. Sample triangle INTERIORS too, not just vertices: every point stays ≥ 0.3 mm and ≤ 3 mm in front of the visor (strict, FAIL otherwise).
- Combinations (morphs add linearly, so they cannot stay exactly on a curved surface): surprised + each look* with the look weight at the runtime cap 0.5 must also pass 0.3–3 mm. At full weight 1.0, only report the gap as INFO, and require it to stay > 0 mm (no intersection). Never bend the look* morphs to make a combo pass: that would break Basis + look*, the most common gaze case.
- After export, re-open the GLB JSON: every mesh "weights" entry is 0, and node names contain no "." characters.
- No mesh object has non-zero rotation or non-unit scale; TRIS_Eyes and TRIS_Mouth have no modifiers.
- Total triangle count and the export path.
Finally print every created object with its parent and world location.

Put the tunable flags at the top of the script: RENDER_PREVIEWS = False, MAKE_ANIMATIONS = False, EXPORT_PATH = "//tris_mascot.glb". Return the complete script in one code block, then explain how to run it.
```

---

## Phiên bản từng bước (dùng với AI điều khiển Blender)

Dán **Master prompt** trước, kèm câu: *"Read the spec only. Do not build anything yet; reply
OK."* Sau đó dán lần lượt từng bước dưới đây. Mỗi bước nhỏ nên dễ kiểm tra và dễ sửa.

**Step 1 — Setup**
```text
Using section 0 of the TRIS spec: set metric units (1 unit = 1 m), create the cleanup routine (delete only TRIS_* objects, MAT_Tris_* materials and their orphan meshes), the sRGB-hex-to-linear helper, a make_material() helper for the Principled BSDF, and a parent_keep_world() helper with identity matrix_parent_inverse. Create all MAT_Tris_* materials from section 7. Print the material list.
```

**Step 2 — Body và đầu**
```text
Build TRIS_Body (section 1) and TRIS_Head (section 2) with bmesh, transforms baked into vertices, origins as specified, smooth shading, Subdivision level 1. Print vertex counts and the world bounding box of each (expected: body z 0.10–0.58, head z 0.605–0.915).
```

**Step 3 — Màn hình mặt**
```text
Build TRIS_Visor as the polar-grid ellipsoid patch from section 3 and TRIS_VisorRim as a mesh tube along its boundary. Verify that every visor face normal has a negative Y component and print min/max of the visor x and z.
```

**Step 4 — Mắt LED và shape key** (bước quan trọng nhất)
```text
Build TRIS_Eyes exactly as section 4: two grid islands (33 columns × 8 rows each, 528 vertices), EVERY vertex projected onto the ×1.016 LED layer (no flattening of columns), Basis = neutral, then the 14 shape keys with the exact names and formulas. Write the shape math as pure Python functions (eye_shape(name, side) -> list of (x, z_top, z_bottom)) so they can be unit-tested, and reuse the same vertex order for every key. Set every key's value to 0 right after creating it (Blender creates keys at 1.0). No modifiers. Print, for every key: vertex count, min/max x and z, whether all points stay inside the visor domain, and the min/max gap to the visor sampled at triangle interiors (must be 0.3–3 mm).
```

**Step 5 — Miệng LED**
```text
Build TRIS_Mouth exactly as section 5 (17 columns × 3 rows = 51 vertices, Basis rounded bar, shape keys aa, oh, smile, frown, every key value reset to 0). No modifiers. Print the same checks as step 4.
```

**Step 6 — Phụ kiện**
```text
Build the accessories from section 6: ears, ear rings, antenna stalk (top hidden inside the star), antenna star, mitten arms (thumb fused by Boolean Union + Voxel Remesh, origin at the shoulder pivot, 12° outward tilt baked in), chest emblem seated on the evaluated subdivided body, hover ring. Use the _L/_R names. Assign materials. Print each object's world origin and bounding box, confirm the arms do not intersect the body (minimum distance > 0), and print the emblem's back-face distance to the evaluated body (must be slightly negative, i.e. seated).
```

**Step 7 — Phân cấp và pivot**
```text
Create the empties TRIS_Root, TRIS_BodyPivot and TRIS_HeadPivot and parent everything as section 8 (identity parent inverse, local location = world − parent world). Verify that no object's world position changed compared with before parenting (tolerance 1e-6). Print the hierarchy tree.
```

**Step 8 — Cảnh xem trước và render**
```text
Build the preview scene from section 9 (camera with Track To, three area lights, world colour, EEVEE 1024×1024). Then render the expression previews and the turnaround into //renders/, using the emotion colour table, and reset all keys and the LED colour afterwards. Print the list of rendered files.
```

**Step 9 — Animation (tùy chọn)**
```text
Create the optional clips Idle, Wave, Hop and Blink from section 10 with keyframe_insert only, push each to NLA tracks named exactly like the clip, clear active actions, and keep tracks unmuted. Print each object's NLA tracks.
```

**Step 10 — Kiểm tra và xuất**
```text
Run every self-check from section 12, print PASS/FAIL, then export the GLB as section 11 and report the file size and triangle count.
```

---

## Prompt sửa lỗi

```text
The script failed in Blender 5.2 with the traceback below. Keep the TRIS spec unchanged (names, numbers, shape-key formulas). Find the root cause, explain it in one sentence, and return only the corrected functions plus the line(s) that call them. Do not rename objects or shape keys.

<dán traceback ở đây>
```

```text
The model was built but <mô tả vấn đề: ví dụ mắt bị chìm vào visor / mặt bị ngược / shape key happy méo>. Diagnose against sections 3–5 of the TRIS spec, print the numbers that prove the cause (normals, y-offsets, vertex order), then fix it.
```

---

## Bảng tra nhanh

### Kích thước chính (mét, Z hướng lên, mặt nhìn về −Y)

| Bộ phận | Tâm / gốc | Kích thước |
|---|---|---|
| Thân `TRIS_Body` | (0, 0, 0.34) | bán trục 0.19 × 0.17 × 0.24, đáy 0.10, đỉnh 0.58, phần trên thu hẹp 18 % |
| Đầu `TRIS_Head` | (0, 0, 0.76) | bán trục 0.20 × 0.17 × 0.155, khe hở 25 mm với thân |
| Màn hình `TRIS_Visor` | theo đầu | elip rộng 0.320 × cao 0.224, lệch xuống 0.010, nổi 1.4 mm |
| Mắt `TRIS_Eyes` | (±0.072, +0.005) so với tâm đầu | oval 0.060 × 0.085, nổi thêm 1.4 mm trên visor |
| Miệng `TRIS_Mouth` | (0, −0.068) so với tâm đầu | thanh 0.032 × 0.0056 |
| Tai `TRIS_Ear_L/_R` | (±0.212, 0.005, 0.765) | trụ R 0.062, dày 0.034, vòng sáng R 0.050 tại x ±0.234 |
| Ăng-ten | thân trụ 0.905→0.985, sao tại z 0.995 | sao R 0.032 / r 0.014, đỉnh khoảng 1.027 |
| Tay `TRIS_Arm_L/_R` | vai (±0.205, 0, 0.52) | găng tay 0.10 × 0.09 × 0.22, nghiêng ra ngoài 12° |
| Huy hiệu `TRIS_Emblem` | mặt trước thân, z 0.42 | sao R 0.030 / r 0.013 |
| Vòng bay `TRIS_HoverRing` | z 0.065 | xuyến R 0.11 / r 0.010 |

### Shape key ↔ cảm xúc trong Companion

| Shape key (`TRIS_Eyes`) | Hình mắt | Màu LED |
|---|---|---|
| *(Basis)* neutral | oval đứng | `#CDD9FF` |
| `happy` | hai cung ∩ cười | `#FFE08A` |
| `love` | trái tim | `#FFB3CF` |
| `sad` | oval xệ khóe ngoài | `#7F93C9` |
| `angry` | oval ép khóe trong | `#FF9D97` |
| `surprised` | tròn to | `#FFFFFF` |
| `curious` | một mắt to, một mắt nhỏ | `#CDD9FF` |
| `thinking` | gạch ngắn liếc lên | `#CDD9FF` |
| `listening` | oval to hơn, hơi nhích lên | `#A5B9FF` |
| `sleepy` | vạch ngang mảnh | `#7F93C9` |
| `blink` | nhắm (dùng cho chớp mắt) | giữ màu |
| `lookLeft/Right/Up/Down` | dịch mắt để nhìn theo chuột | giữ màu |

`TRIS_Mouth`: `aa` (há, dùng cho lipsync), `oh`, `smile`, `frown`.
Màu và tên cảm xúc khớp bảng `EXPRESSIONS` trong `frontend/public/companion/index.html`.

---

## Kiểm tra sau khi dựng

- [ ] Front view (Numpad 1) thấy mặt robot, mắt nằm trên màn hình đen, không bị chìm.
- [ ] Object Data Properties → **Shape Keys** của `TRIS_Eyes` có Basis + 14 key; kéo từng slider
      thì mắt đổi hình mượt, không có mặt bị lật đen.
- [ ] `TRIS_Eyes`, `TRIS_Mouth` **không có modifier** (nếu có, exporter sẽ bỏ shape key).
- [ ] Trước khi export, **mọi slider shape key đều ở 0**. Nếu quên, GLB mở lên sẽ bật cùng lúc 14 biểu cảm.
- [ ] Nhìn nghiêng (Numpad 3): mắt nằm sát màn hình, không lồi ra ngoài đường viền mặt.
- [ ] Chọn `TRIS_HeadPivot` rồi xoay (R) thì cả cụm đầu, mắt, tai, ăng-ten xoay quanh cổ.
- [ ] Mọi mesh có Rotation 0 và Scale 1 (N panel → Item).
- [ ] Xuất GLB rồi mở ở <https://gltf-viewer.donmccurdy.com/>: thấy morph targets đúng tên,
      vật liệu phát sáng (emissive strength) còn giữ.

## Lỗi thường gặp

| Hiện tượng | Nguyên nhân / cách sửa |
|---|---|
| Shape key biến mất trong GLB | Mesh có modifier, hoặc thiếu **Shape Keys** khi export → bỏ modifier khỏi Eyes/Mouth, bật `export_morph`. |
| Mắt nhấp nháy lẫn vào màn hình (z-fighting) | Lớp LED phải ở ×1.016, visor ở ×1.008, không đặt cùng một mặt. |
| Mắt rỗng ruột, chỉ thấy viền | Mỗi cột mắt chỉ có 2 hàng nên phần giữa chìm sau visor → dùng 8 hàng, chiếu từng đỉnh lên lớp LED. |
| Mắt lồi khỏi mặt khi nhìn nghiêng | Cột mắt bị ép cùng một độ sâu → bỏ cách đó, dùng lưới 8 hàng. |
| Mở GLB thấy mắt to bất thường, tràn khỏi màn hình | Shape key mới tạo có giá trị 1.0 và được xuất làm trọng số mặc định → đặt mọi key về 0 trước khi export. |
| Màu cảm xúc gần như trắng hết | Emission Strength > 1 hoặc View Transform AgX → strength 1.0, Base Color đen, View Transform Standard. |
| three.js không tìm thấy `TRIS_Arm.L` | three.js bỏ dấu chấm khỏi tên node → đặt tên `TRIS_Arm_L`. |
| Mắt/miệng bị đen khi nhìn từ trước | Pháp tuyến ngược: thứ tự đỉnh của quad phải là (bottom_j, bottom_j+1, top_j+1, top_j). |
| `AttributeError: use_auto_smooth` | API cũ, đã bị xóa từ 4.1 → dùng `polygon.use_smooth`. |
| `KeyError: 'Emission'` / `'Specular'` | Tên socket cũ → dùng `Emission Color`, `Specular IOR Level`, `Coat Weight`. |
| `action.fcurves` lỗi | API Action cũ đã bị xóa ở 5.x → chỉ dùng `keyframe_insert()`. |
| Model nằm ngang trong three.js | Quên `export_yup=True`. |
| Companion báo "Tệp không chứa dữ liệu VRM" | Companion hiện chỉ nạp `.vrm`; cần thêm chế độ đọc GLB và điều khiển shape key / pivot theo tên ở trên. |
