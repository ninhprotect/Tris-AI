"""Local text-to-image / GIF / short-video generation for Tris AI.

Runs inside runtime/imagegen/.venv (isolated torch CUDA environment) and is
invoked by services/image_gen.py as a subprocess. Prints the output path as
the final stdout line so the caller can pick it up.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def build_pipeline(model: str, device: str):
    import torch
    from diffusers import AutoPipelineForText2Image

    dtype = torch.float16 if device == "cuda" else torch.float32
    try:
        pipe = AutoPipelineForText2Image.from_pretrained(
            model, variant="fp16", torch_dtype=dtype, safety_checker=None, local_files_only=True
        )
    except Exception:
        # Some checkpoints do not ship an fp16 variant.
        pipe = AutoPipelineForText2Image.from_pretrained(
            model, torch_dtype=dtype, safety_checker=None, local_files_only=True
        )
    pipe = pipe.to(device)
    pipe.set_progress_bar_config(disable=True)
    if device == "cuda":
        pipe.enable_attention_slicing()
    return pipe


def report(event: dict) -> None:
    """Emit one machine-readable progress line; the parent streams it live."""
    print("PROGRESS " + json.dumps(event, ensure_ascii=False), flush=True)


def render(pipe, prompt: str, model: str, steps: int, width: int, height: int, seed: int):
    import torch

    # CLIP silently truncates long descriptions otherwise, losing requested
    # subjects/exclusions at the end. Ask for a shorter prompt instead.
    token_ids = pipe.tokenizer(prompt, truncation=False)["input_ids"]
    if len(token_ids) > pipe.tokenizer.model_max_length:
        raise ValueError(
            "Image description exceeds the model text limit; please shorten it "
            "while keeping the subject, colors and important details."
        )
    generator = torch.Generator(device=pipe.device.type).manual_seed(seed)
    guidance = 0.0 if "turbo" in model.lower() else 7.5
    total = max(1, steps)

    def step_callback(pipe, step_index, timestep, kwargs):
        report({"stage": "step", "step": step_index + 1, "total": total})
        return kwargs

    return pipe(
        prompt=prompt,
        num_inference_steps=total,
        guidance_scale=guidance,
        width=width,
        height=height,
        generator=generator,
        callback_on_step_end=step_callback,
    ).images[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["image", "gif", "video"], default="image")
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--model", default="stabilityai/sd-turbo")
    args = parser.parse_args()

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        pipe = build_pipeline(args.model, device)
    except torch.cuda.OutOfMemoryError:
        print("CUDA out of memory, retrying on CPU", file=sys.stderr)
        device = "cpu"
        pipe = build_pipeline(args.model, device)

    base_seed = args.seed if args.seed >= 0 else random.randint(0, 2**31 - 1)
    count = 1 if args.mode == "image" else max(2, min(args.frames, 16))
    images = []
    try:
        for index in range(count):
            if count > 1:
                report({"stage": "frame", "frame": index + 1, "total": count})
            seed = base_seed + index * 97
            images.append(
                render(pipe, args.prompt, args.model, args.steps, args.width, args.height, seed)
            )
    except torch.cuda.OutOfMemoryError:
        print("CUDA out of memory mid-run, retrying on CPU", file=sys.stderr)
        del pipe
        torch.cuda.empty_cache()
        pipe = build_pipeline(args.model, "cpu")
        images = [
            render(pipe, args.prompt, args.model, args.steps, args.width, args.height, base_seed + i * 97)
            for i in range(count)
        ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "image":
        images[0].save(out)
    elif args.mode == "gif":
        images[0].save(
            out, save_all=True, append_images=images[1:], duration=500, loop=0
        )
    else:
        import imageio.v2 as imageio
        import numpy as np

        writer = imageio.get_writer(str(out), fps=2)
        for image in images:
            writer.append_data(np.asarray(image))
        writer.close()
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
