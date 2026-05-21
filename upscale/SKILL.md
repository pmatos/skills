---
name: upscale
description: Upscale raster images with a local OpenCV EDSR super-resolution model, then produce an exact target pixel size. Use when the user asks to upscale, enlarge, super-resolve, make a higher-resolution version, or create a wallpaper/print-size raster from an existing image while preserving the original artwork.
argument-hint: "<image path> [target size or scale]"
user-invocable: true
---

# Upscale

Create a real local super-resolution upscale from an existing raster image. Prefer this over image generation when the user wants the same image at a larger, verified pixel size.

## Workflow

1. Identify the source image path. If the image was attached in the current conversation, use the local image path from the session context.
2. Pick the exact output size:
   - If the user gives dimensions, use them exactly.
   - If they give only a multiplier, use `--factor`.
   - If the requested aspect ratio differs from the source, choose `--fit stretch` only when exact full-frame dimensions matter and the mismatch is small. Use `--fit cover` to preserve aspect by cropping, or `--fit contain` to preserve aspect by padding.
3. Run the bundled script:

```bash
uv run "/path/to/upscale/scripts/upscale_image.py" \
  "/path/to/source.png" \
  --size 5120x2160 \
  --output "/path/to/output.png" \
  --fit stretch \
  --keep-raw
```

Resolve `/path/to/upscale` relative to this skill directory. If `uv` is unavailable, create a temporary Python venv, install `opencv-contrib-python-headless pillow numpy`, and run the script with that venv's Python.

4. Verify the final file:

```bash
magick identify -format '%f %wx%h %[colorspace] %[channels]\n' "/path/to/output.png"
file "/path/to/output.png"
```

Report the final path and the verified dimensions. If `--keep-raw` was used, mention the raw EDSR output path when useful.

## Script Notes

- The script downloads EDSR `.pb` models into `~/.cache/codex-upscale/models/` on first use.
- Default model selection is `auto`: it chooses the smallest EDSR scale (`x2`, `x3`, or `x4`) that exceeds the requested target dimensions before final resizing.
- It processes large images in overlapping tiles to avoid huge memory spikes and reduce visible tile seams.
- The previous RR880 workflow used OpenCV `dnn_superres` with `EDSR_x3`, wrote a raw SR image, then resized to exactly `5120x2160`.

## Quality Rules

- Do not call a plain ImageMagick resize a real upscale. Use the EDSR script first, then resize to exact dimensions.
- Do not silently trust requested dimensions. Always inspect the generated file after writing it.
- If a faster model or Real-ESRGAN introduces block/tile artifacts, reject that output and keep the cleaner EDSR result.
- Preserve the source file; write outputs to a new path.
