import io
import random

from PIL import Image


def test_optimize_for_bluesky_compresses_under_1mb(tmp_path):
    from app.core.image_optimize import BSKY_MAX_IMAGE_BYTES, optimize_for_bluesky

    # Create a deterministic, hard-to-compress PNG (random pixels) so the optimizer
    # has to resize/quality-adjust.
    w, h = 1800, 1800
    rng = random.Random(0)
    raw = rng.randbytes(w * h * 3)
    im = Image.frombytes("RGB", (w, h), raw)

    p = tmp_path / "big.png"
    im.save(p, format="PNG")

    out = optimize_for_bluesky(str(p), "image/png")

    assert out["out_mime"] == "image/jpeg"
    assert out["out_ext"] == ".jpg"
    assert out["size_bytes"] <= BSKY_MAX_IMAGE_BYTES
    assert isinstance(out["bytes"], (bytes, bytearray))
    assert len(out["bytes"]) == out["size_bytes"]
    assert out["width"] > 0 and out["height"] > 0
    assert out["quality"] >= 45

    # Ensure result bytes are a decodable JPEG.
    img2 = Image.open(io.BytesIO(out["bytes"]))
    assert img2.format == "JPEG"
