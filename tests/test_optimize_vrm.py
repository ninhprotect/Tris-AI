"""Tests for the VRM/GLB texture optimizer (scripts/optimize_vrm.py)."""
import io
import struct
import unittest

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

from scripts.optimize_vrm import optimize_glb, read_glb, write_glb


def make_png(width: int, height: int) -> bytes:
    frame = Image.effect_noise((width, height), 64).convert("RGB")
    out = io.BytesIO()
    frame.save(out, "PNG")
    return out.getvalue()


def make_glb(image_bytes: bytes) -> bytes:
    """Minimal GLB: one PNG image embedded as bufferView + one texture."""
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "root"}],
        "buffers": [{"byteLength": len(image_bytes)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(image_bytes)}],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [{"name": "m", "pbrMetallicRoughness": {}}],
    }
    return write_glb(gltf, image_bytes)


@unittest.skipUnless(HAVE_PIL, "Pillow is required")
class OptimizeVrmTests(unittest.TestCase):
    def test_oversized_png_becomes_small_webp_with_extension(self):
        original_png = make_png(2048, 2048)
        glb = make_glb(original_png)
        optimized, report = optimize_glb(glb, max_size=1024, quality=85)
        self.assertLess(len(optimized), len(glb) / 2, "optimizer must shrink a noisy 2048 PNG drastically")
        gltf, blob = read_glb(optimized)
        image = gltf["images"][0]
        self.assertEqual(image["mimeType"], "image/webp")
        self.assertIn("EXT_texture_webp", gltf["extensionsUsed"])
        self.assertEqual(gltf["textures"][0]["extensions"]["EXT_texture_webp"]["source"], 0)
        view = gltf["bufferViews"][image["bufferView"]]
        frame = Image.open(io.BytesIO(blob[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]))
        self.assertLessEqual(max(frame.size), 1024)
        self.assertTrue(any("webp" in line for line in report))

    def test_small_webp_is_left_untouched(self):
        small = io.BytesIO()
        Image.new("RGB", (512, 512)).save(small, "WEBP", quality=85)
        webp_bytes = small.getvalue()
        glb = make_glb(webp_bytes)
        gltf, _ = read_glb(glb)
        gltf["images"][0]["mimeType"] = "image/webp"
        glb = write_glb(gltf, webp_bytes)
        optimized, _ = optimize_glb(glb, max_size=1024)
        gltf_out, blob_out = read_glb(optimized)
        self.assertEqual(gltf_out["images"][0]["mimeType"], "image/webp")
        view = gltf_out["bufferViews"][gltf_out["images"][0]["bufferView"]]
        self.assertEqual(blob_out[view["byteOffset"]:view["byteOffset"] + view["byteLength"]], webp_bytes)

    def test_non_glb_rejected(self):
        with self.assertRaises(ValueError):
            optimize_glb(b"not a glb file at all")

    def test_buffers_length_updated(self):
        glb = make_glb(make_png(2048, 2048))
        optimized, _ = optimize_glb(glb, max_size=512)
        gltf, blob = read_glb(optimized)
        # buffer.byteLength là dữ liệu thật; blob có thể dài hơn tối đa 3 byte padding.
        self.assertTrue(0 <= len(blob) - gltf["buffers"][0]["byteLength"] < 4)


if __name__ == "__main__":
    unittest.main()
