#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
#   "opencv-contrib-python-headless>=4.10",
#   "pillow>=10.0",
# ]
# ///
"""Upscale an image with OpenCV EDSR and write an exact target size."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageOps

MODEL_URLS = {
    2: "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x2.pb",
    3: "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x3.pb",
    4: "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x4.pb",
}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_size(value: str) -> tuple[int, int]:
    text = value.lower().replace(" ", "")
    for sep in ("x", "×", ","):
        if sep in text:
            left, right = text.split(sep, 1)
            width, height = int(left), int(right)
            if width <= 0 or height <= 0:
                raise argparse.ArgumentTypeError("size must be positive")
            return width, height
    raise argparse.ArgumentTypeError("size must look like WIDTHxHEIGHT")


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "codex-upscale"


def download_model(scale: int, cache_dir: Path) -> Path:
    model_dir = cache_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"EDSR_x{scale}.pb"
    if model_path.exists() and model_path.stat().st_size > 0:
        return model_path

    url = MODEL_URLS[scale]
    tmp_path = model_path.with_suffix(".pb.tmp")
    log(f"download EDSR_x{scale}: {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            tmp_path.write_bytes(response.read())
    except urllib.error.URLError as exc:
        raise SystemExit(f"failed to download {url}: {exc}") from exc
    tmp_path.replace(model_path)
    return model_path


def choose_scale(src_width: int, src_height: int, target: tuple[int, int] | None, factor: int) -> int:
    if target is None:
        return factor
    target_width, target_height = target
    for scale in (2, 3, 4):
        if src_width * scale >= target_width and src_height * scale >= target_height:
            return scale
    return 4


def intervals(length: int, step: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    while start < length:
        end = min(length, start + step)
        spans.append((start, end))
        start = end
    return spans


def edsr_upscale(img: np.ndarray, model_path: Path, scale: int, tile_size: int, overlap: int) -> np.ndarray:
    height, width = img.shape[:2]
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(str(model_path))
    sr.setModel("edsr", scale)

    out = np.empty((height * scale, width * scale, 3), dtype=np.uint8)
    xs = intervals(width, tile_size)
    ys = intervals(height, tile_size)
    total = len(xs) * len(ys)
    done = 0

    for row, (core_y0, core_y1) in enumerate(ys, start=1):
        for col, (core_x0, core_x1) in enumerate(xs, start=1):
            tile_x0 = max(0, core_x0 - overlap)
            tile_x1 = min(width, core_x1 + overlap)
            tile_y0 = max(0, core_y0 - overlap)
            tile_y1 = min(height, core_y1 + overlap)

            tile = img[tile_y0:tile_y1, tile_x0:tile_x1]
            up = sr.upsample(tile)

            src_x0 = (core_x0 - tile_x0) * scale
            src_x1 = src_x0 + (core_x1 - core_x0) * scale
            src_y0 = (core_y0 - tile_y0) * scale
            src_y1 = src_y0 + (core_y1 - core_y0) * scale

            out[
                core_y0 * scale : core_y1 * scale,
                core_x0 * scale : core_x1 * scale,
            ] = up[src_y0:src_y1, src_x0:src_x1]
            done += 1
            log(f"tile {done}/{total} ({col},{row})")

    return out


def fit_image(image: Image.Image, target: tuple[int, int], mode: str, background: str) -> Image.Image:
    width, height = target
    if mode == "stretch":
        return image.resize((width, height), Image.Resampling.LANCZOS)
    if mode == "cover":
        return ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    if mode == "contain":
        contained = ImageOps.contain(image, (width, height), method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), ImageColor.getrgb(background))
        canvas.paste(contained, ((width - contained.width) // 2, (height - contained.height) // 2))
        return canvas
    raise ValueError(f"unknown fit mode: {mode}")


def output_default(src: Path, target: tuple[int, int] | None, factor: int) -> Path:
    if target is None:
        suffix = f"x{factor}"
    else:
        suffix = f"{target[0]}x{target[1]}"
    return src.with_name(f"{src.stem}-upscaled-{suffix}.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="source raster image")
    parser.add_argument("--output", "-o", type=Path, help="output image path")
    parser.add_argument("--size", type=parse_size, help="exact final size, e.g. 5120x2160")
    parser.add_argument("--factor", type=int, choices=(2, 3, 4), default=2, help="scale factor when --size is omitted")
    parser.add_argument("--model-scale", choices=("auto", "2", "3", "4"), default="auto")
    parser.add_argument("--fit", choices=("stretch", "cover", "contain"), default="stretch")
    parser.add_argument("--background", default="#000000", help="padding color for --fit contain")
    parser.add_argument("--tile-size", type=int, default=512, help="source-space tile core size")
    parser.add_argument("--overlap", type=int, default=96, help="source-space tile overlap")
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--raw-output", type=Path, help="optional path for raw EDSR output before final resize")
    parser.add_argument("--keep-raw", action="store_true", help="write a raw EDSR image next to the final output")
    args = parser.parse_args()

    src = args.input.expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"input does not exist: {src}")
    if args.tile_size <= 0:
        raise SystemExit("--tile-size must be positive")
    if args.overlap < 0:
        raise SystemExit("--overlap must be non-negative")

    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"failed to read image: {src}")

    src_height, src_width = img.shape[:2]
    target = args.size if args.size is not None else (src_width * args.factor, src_height * args.factor)
    if args.model_scale == "auto":
        scale = choose_scale(src_width, src_height, args.size, args.factor)
    else:
        scale = int(args.model_scale)
    if src_width * scale < target[0] or src_height * scale < target[1]:
        log(
            "warning: target exceeds raw EDSR canvas; final resize will still enlarge "
            f"from {src_width * scale}x{src_height * scale} to {target[0]}x{target[1]}"
        )

    target_aspect = target[0] / target[1]
    source_aspect = src_width / src_height
    aspect_delta = abs(target_aspect - source_aspect) / source_aspect
    if args.fit == "stretch" and aspect_delta > 0.01:
        log(f"warning: stretching aspect ratio by {aspect_delta:.1%}; use --fit cover or --fit contain to preserve aspect")

    output = args.output.expanduser().resolve() if args.output else output_default(src, args.size, args.factor)
    output.parent.mkdir(parents=True, exist_ok=True)

    model_path = download_model(scale, args.cache_dir.expanduser())
    log(f"source {src_width}x{src_height}; EDSR_x{scale}; final {target[0]}x{target[1]}; fit={args.fit}")
    raw = edsr_upscale(img, model_path, scale, args.tile_size, args.overlap)

    raw_output = args.raw_output
    if raw_output is None and args.keep_raw:
        raw_output = output.with_name(f"{output.stem}-edsr-x{scale}-raw.png")
    if raw_output is not None:
        raw_path = raw_output.expanduser().resolve()
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(raw_path), raw)
        log(f"raw {raw.shape[1]}x{raw.shape[0]} -> {raw_path}")

    rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    final = fit_image(Image.fromarray(rgb).convert("RGB"), target, args.fit, args.background).convert("RGB")
    final.save(output)

    with Image.open(output) as check:
        if check.size != target:
            raise SystemExit(f"verification failed: wrote {check.size[0]}x{check.size[1]}, expected {target[0]}x{target[1]}")
    print(output)
    print(f"verified {target[0]}x{target[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
