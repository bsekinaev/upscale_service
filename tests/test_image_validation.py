"""Image format/size boundary checks, independent of Redis and the EDSR model."""

import io

import pytest
from PIL import Image

import image_validation as checks
import upscale


def make_image(fmt="PNG", width=16, height=16):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "navy").save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("fmt", "filename"),
    [
        ("PNG", "image.PNG"),
        ("JPEG", "image.JpG"),
        ("BMP", "image.bmp"),
        ("TIFF", "image.tif"),
    ],
)
def test_supported_real_image_formats(fmt, filename):
    checks.validate_image_bytes(make_image(fmt), filename)


def test_empty_and_malformed_content_rejected():
    for content in (b"", b"\x00" * 128):
        with pytest.raises(checks.ImageValidationError) as err:
            checks.validate_image_bytes(content, "valid.png")
        assert err.value.code == "invalid_image"


def test_extension_and_signature_must_match():
    with pytest.raises(checks.ImageValidationError) as err:
        checks.validate_image_bytes(make_image("PNG"), "spoof.jpg")
    assert err.value.code == "image_extension_mismatch"


def test_dimensions_are_bounded_before_decode(monkeypatch):
    monkeypatch.setattr(checks, "MAX_IMAGE_PIXELS", 15)
    with pytest.raises(checks.ImageValidationError) as err:
        checks.validate_image_bytes(make_image("PNG", 4, 4))
    assert err.value.status_code == 413
    assert err.value.code == "image_dimensions_exceeded"


def test_image_byte_limit(monkeypatch):
    monkeypatch.setattr(checks, "MAX_IMAGE_BYTES", 8)
    with pytest.raises(checks.ImageValidationError) as err:
        checks.validate_image_bytes(make_image("PNG"))
    assert err.value.code == "file_too_large"


def test_worker_revalidates_malformed_bytes_before_model_load(monkeypatch):
    monkeypatch.setattr(
        upscale, "_load_scaler", lambda *a, **k: pytest.fail("model was loaded")
    )
    with pytest.raises(checks.ImageValidationError):
        upscale.upscale_bytes(b"not-a-real-image")


def test_worker_checks_opencv_decoded_dimensions(monkeypatch):
    import numpy as np

    monkeypatch.setattr(upscale, "validate_image_bytes", lambda _: None)
    monkeypatch.setattr(upscale, "MAX_IMAGE_PIXELS", 4)
    monkeypatch.setattr(upscale.cv2, "imdecode", lambda *_: np.zeros((3, 3, 3), dtype=np.uint8))
    monkeypatch.setattr(
        upscale, "_load_scaler", lambda *a, **k: pytest.fail("model was loaded")
    )
    with pytest.raises(ValueError, match="image_dimensions_exceeded"):
        upscale.upscale_bytes(make_image())
