"""Shrink a .vrm/.glb avatar by re-encoding its embedded textures to WebP.

Textures are almost all of a VRoid model's weight (often 10-20 MB of PNG);
downscaling to 1024 px WebP usually cuts the file to a fraction with no
visible loss at Companion's canvas size. Meshes and VRM extensions pass
through untouched.

Usage:
    .venv\\Scripts\\python.exe scripts\\optimize_vrm.py input.vrm [-o out.vrm]
        [--max-size 1024] [--quality 85]

Only standard-library + Pillow are used. The result keeps the .vrm/GLB
structure, so three.js + three-vrm (Companion) loads it as-is via the
EXT_texture_webp extension.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import struct
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Cần Pillow: .venv\\Scripts\\python.exe -m pip install pillow")
    sys.exit(1)

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 20 or struct.unpack_from("<I", data, 0)[0] != GLB_MAGIC:
        raise ValueError("Không phải tệp GLB (.vrm/.glb).")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != JSON_CHUNK:
        raise ValueError("Chunk JSON của GLB không hợp lệ.")
    gltf = json.loads(data[20:20 + json_len])
    offset = 20 + json_len
    bin_data = b""
    if offset + 8 <= len(data):
        bin_len, bin_type = struct.unpack_from("<II", data, offset)
        if bin_type == BIN_CHUNK:
            bin_data = data[offset + 8:offset + 8 + bin_len]
    return gltf, bin_data


def write_glb(gltf: dict, bin_data: bytes) -> bytes:
    json_bytes = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_data = bytes(bin_data)
    bin_data += b"\x00" * ((4 - len(bin_data) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    out = struct.pack("<III", GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(json_bytes), JSON_CHUNK) + json_bytes
    out += struct.pack("<II", len(bin_data), BIN_CHUNK) + bin_data
    return out


def image_bytes(gltf: dict, blob: bytes, image: dict) -> bytes | None:
    if image.get("bufferView") is not None:
        view = gltf["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        return blob[start:start + view["byteLength"]]
    uri = image.get("uri", "")
    if uri.startswith("data:"):
        try:
            return base64.b64decode(uri.split(",", 1)[1])
        except Exception:
            return None
    return None


def optimize_glb(data: bytes, max_size: int = 1024, quality: int = 85) -> tuple[bytes, list[str]]:
    gltf, blob = read_glb(data)
    images = gltf.get("images") or []
    report: list[str] = []

    # Pass 1: quyết định nội dung webp thay thế cho từng texture quá tải.
    replacement: dict[int, bytes] = {}
    for index, image in enumerate(images):
        if image.get("bufferView") is None:
            report.append(f"texture {index}: bỏ qua (không nhúng trong tệp)")
            continue
        view_index = image["bufferView"]
        if view_index in replacement:
            continue
        source = image_bytes(gltf, blob, image)
        if not source:
            report.append(f"texture {index}: bỏ qua (không đọc được)")
            continue
        try:
            frame = Image.open(io.BytesIO(source))
            frame.load()
        except Exception:
            report.append(f"texture {index}: bỏ qua (định dạng lạ)")
            continue
        width, height = frame.size
        if image.get("mimeType") == "image/webp" and max(width, height) <= max_size:
            report.append(f"texture {index}: đã là webp {width}×{height}, giữ nguyên")
            continue
        if max(width, height) > max_size:
            scale = max_size / max(width, height)
            frame = frame.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
        out = io.BytesIO()
        frame.save(out, "WEBP", quality=quality)
        new_bytes = out.getvalue()
        if len(new_bytes) >= len(source):
            report.append(f"texture {index}: webp không nhỏ hơn, giữ nguyên")
            continue
        replacement[view_index] = new_bytes
        image["mimeType"] = "image/webp"
        image.pop("uri", None)
        report.append(
            f"texture {index}: {width}×{height} {len(source) // 1024} KB → "
            f"{frame.size[0]}×{frame.size[1]} {len(new_bytes) // 1024} KB webp"
        )

    # Pass 2: dựng lại binary gọn — chỉ giữ dữ liệu mà bufferView còn dùng,
    # texture nặng được thay bằng webp; mọi offset được remap.
    views = gltf.get("bufferViews") or []
    payload = bytearray()
    for index, view in enumerate(views):
        segment = replacement.get(index)
        if segment is None:
            start = view.get("byteOffset", 0)
            segment = bytes(blob[start:start + view.get("byteLength", 0)])
        payload.extend(b"\x00" * ((-len(payload)) % 4))
        view["byteOffset"] = len(payload)
        view["byteLength"] = len(segment)
        payload.extend(segment)

    textures = gltf.get("textures") or []
    if any(img.get("mimeType") == "image/webp" for img in images):
        used = gltf.setdefault("extensionsUsed", [])
        if "EXT_texture_webp" not in used:
            used.append("EXT_texture_webp")
        for texture in textures:
            source_index = texture.get("source")
            if source_index is not None and images[source_index].get("mimeType") == "image/webp":
                extensions = texture.setdefault("extensions", {})
                extensions["EXT_texture_webp"] = {"source": source_index}

    buffers = gltf.get("buffers") or []
    if buffers:
        buffers[0]["byteLength"] = len(payload)
    return write_glb(gltf, payload), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Tệp .vrm/.glb gốc")
    parser.add_argument("-o", "--output", help="Tệp kết quả (mặc định: <input>.opt.vrm cạnh tệp gốc)")
    parser.add_argument("--max-size", type=int, default=1024, help="Kích thước texture tối đa (px)")
    parser.add_argument("--quality", type=int, default=85, help="Chất lượng WebP (1-100)")
    args = parser.parse_args()

    source_path = Path(args.input)
    if not source_path.is_file():
        print(f"Không thấy tệp {source_path}")
        return 1
    output_path = Path(args.output) if args.output else source_path.with_suffix(".opt.vrm")
    original = source_path.read_bytes()
    optimized, report = optimize_glb(original, args.max_size, args.quality)
    if output_path.resolve() != source_path.resolve():
        output_path.write_bytes(optimized)
    else:
        source_path.write_bytes(optimized)
    for line in report:
        print(line)
    print(
        f"Xong: {len(original) / 1e6:.1f} MB → {len(optimized) / 1e6:.1f} MB "
        f"({100 * len(optimized) / max(1, len(original)):.0f}%) → {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
