# Prompt ảnh nền sân khấu Companion (gửi ChatGPT)

Gửi ChatGPT khối prompt bên dưới, kèm ảnh mẫu (phòng lưới xanh đen). Ảnh nền nằm sau cả 3 chế độ
(Linh vật 2D, Tris 3D, Model VRM) vì canvas 3D trong suốt. Companion chỉ có giao diện tối, nên prompt
nhắm vào nền tối.

Những điểm prompt chặn trước để ảnh không "lỗi" khi lên web:
- Sân khấu đổi tỉ lệ theo cửa sổ (gần vuông trên laptop/điện thoại, 4:3–16:9 trên màn rộng) và ảnh
  được cắt quanh tâm, nên bố cục phải đối xứng và không có gì quan trọng ở mép trái/phải.
- Lưới thưa, nét 2–3 px: lưới dày nét 1 px như ảnh mẫu sẽ bị nhòe/răng cưa (moiré) khi trình duyệt thu nhỏ.
- Nền tối, độ tương phản thấp, vùng sau lưng linh vật "yên": linh vật vỏ trắng + LED xanh phải là thứ
  sáng nhất trên sân khấu.
- Không chữ, logo, đồ vật, quầng sáng: Companion đã tự vẽ quầng sáng khi Tris nói.

---

```text
Create ONE background image for the stage of my web app. A small cute robot mascot stands in the middle
of this stage, drawn on top of the image, in one of two looks the user can switch between:
- 3D look: glossy white shell, dark visor face with glowing cyan-blue LED eyes.
- 2D look: dark charcoal rounded-square body (about #2b2f3a) with a light periwinkle outline (#a5b9ff).
The background must work behind BOTH looks. Use the attached image only as a style reference: an empty
room made of a thin grid, one-point perspective. Goal: modern, minimal, calm, and clean at any screen size.

## Size and composition
- Landscape 1536 x 1024 px, PNG.
- Perfectly symmetric one-point perspective. Vanishing point exactly at the horizontal center, about 45%
  from the top.
- Back wall: a rectangle centered horizontally, spanning about 25%-75% of the width and 22%-70% of the
  height. The seam between back wall and floor sits at about 70% of the height.
- The web page crops this image, always around the center, to anything from a square (1:1) to 16:9. So
  nothing important may sit in the outer 18% on the left and right, and the room must still read as a
  room when cropped to a square.
- Completely empty room: no objects, furniture, people, characters, text, numbers, logos, watermark,
  signature, UI elements or frames.

## Style
- Flat, clean, minimal digital style. No texture, no photorealism, no reflections on the floor.
- Colors: base deep blue-charcoal around #141821 to #1b2130 (not saturated navy, not pure black). The
  middle of the back wall only slightly lighter (around #1e2636). Corners and outer edges fade darker,
  toward #121419.
- Grid lines: cool blue-grey around #8fa6c8 at low contrast (roughly 20-30% visible). The back-wall grid
  is the faintest of all, so the area behind the mascot stays quiet; side walls and floor slightly clearer.
  Optionally a tiny dot at each grid intersection in the same color.
- Grid density: about 10-12 cells across the back wall, much sparser than the reference. Lines 2-3 px
  thick and anti-aliased, so the image stays clean (no moire, no shimmering) when the browser scales it
  down to about 900 px wide.
- No glow halo, light rays, lens flare, bokeh, neon, fog, stars, particles or spotlights (the app draws
  its own glow). Add very slight fine noise (1-2%) only to prevent visible color banding in gradients.

## Contrast rule
The 3D mascot must be the brightest thing on the stage, and the dark 2D body must still separate from
the background. Keep the whole image dark and low-contrast: apart from the thin grid lines, nothing may
be brighter than about #3a4560, and the center area (behind the mascot) must stay darker than #22293a.

Deliver exactly one 1536 x 1024 PNG.
```

---

Có ảnh rồi: gửi lại cho Claude để nén sang WebP và kiểm tra trên cả 3 chế độ. Hoặc tự chép vào cả hai
thư mục, đặt tên `stage.png` (hoặc `stage.webp`):

- `frontend/public/companion/backgrounds/`
- `frontend/dist/companion/backgrounds/`

Sau đó tải lại trang Companion (Ctrl+F5). Không có tệp thì sân khấu giữ nền gradient như cũ.
