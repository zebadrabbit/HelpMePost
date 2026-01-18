from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image


BSKY_MAX_IMAGE_BYTES = 1_000_000


class ImageOptimizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptimizationResult:
    data: bytes
    out_mime: str
    out_ext: str
    width: int
    height: int
    quality: int
    size_bytes: int
    changed: bool


def _resize_to_max_side(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_side:
        return img

    if w >= h:
        new_w = max_side
        new_h = max(1, int(round(h * (max_side / float(w)))))
    else:
        new_h = max_side
        new_w = max(1, int(round(w * (max_side / float(h)))))

    # LANCZOS gives good downscaling quality.
    return img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    # Strip metadata by not forwarding EXIF and using a fresh save.
    img.save(buf, format="JPEG", quality=int(quality), optimize=True, progressive=True)
    return buf.getvalue()


def optimize_for_bluesky(input_path: str, mime: str) -> dict:
    """Optimize an image for Bluesky's 1,000,000-byte uploadBlob limit.

    Algorithm (deterministic):
    - Loads via Pillow
    - Converts to RGB (drops alpha), outputs JPEG
    - Strips metadata (does not preserve EXIF)
    - Starts with max_side=1600 and quality=85
    - If still >1MB: decreases quality stepwise down to 45
    - If still >1MB at quality 45: shrinks max_side (x0.85), resets quality to 75, repeats
    - Hard stop: if max_side < 640 and still >1MB, raise ImageOptimizationError

    Returns a dict with keys:
      bytes, out_mime, out_ext, width, height, quality, size_bytes, changed
    """

    if not mime or not mime.lower().startswith("image/"):
        raise ImageOptimizationError("Unsupported mime for image optimization")

    try:
        with Image.open(input_path) as im:
            im.load()
            src_w, src_h = im.size
            src_mode = im.mode

            # Normalize to RGB for JPEG output.
            rgb = im.convert("RGB")

            max_side = 1600
            quality_steps = [85, 75, 65, 55, 45]

            # Loop: resize (if needed) then attempt multiple quality levels.
            current = _resize_to_max_side(rgb, max_side)
            chosen_quality = quality_steps[0]
            encoded = b""

            while True:
                for q in quality_steps:
                    chosen_quality = q
                    encoded = _encode_jpeg(current, q)
                    if len(encoded) <= BSKY_MAX_IMAGE_BYTES:
                        w, h = current.size
                        changed = (
                            mime.lower() != "image/jpeg"
                            or (src_w, src_h) != (w, h)
                            or src_mode != "RGB"
                        )
                        return {
                            "bytes": encoded,
                            "out_mime": "image/jpeg",
                            "out_ext": ".jpg",
                            "width": int(w),
                            "height": int(h),
                            "quality": int(chosen_quality),
                            "size_bytes": int(len(encoded)),
                            "changed": bool(changed),
                        }

                # If we're here, even quality 45 wasn't enough.
                max_side = int(max_side * 0.85)
                if max_side < 640:
                    raise ImageOptimizationError("cannot_compress_under_limit")

                # Resize again smaller and retry with a slightly higher starting quality.
                current = _resize_to_max_side(rgb, max_side)
                quality_steps = [75, 65, 55, 45]

    except ImageOptimizationError:
        raise
    except Exception as e:
        raise ImageOptimizationError("failed_to_optimize") from e
