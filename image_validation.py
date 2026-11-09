"""Bounded, signature-aware validation shared by HTTP and Celery worker."""

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "4000000"))
MAX_IMAGE_SIDE = int(os.getenv("MAX_IMAGE_SIDE", "4096"))

EXTENSION_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}
ALLOWED_FORMATS = frozenset(EXTENSION_FORMATS.values())


class ImageValidationError(ValueError):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def validate_image_bytes(data: bytes, filename: str | None = None) -> None:
    """Validate encoded length, true format and dimensions before OpenCV decode.

    Filename is optional for worker-side revalidation. PIL reads metadata and
    verifies encoding, while OpenCV performs the actual decode and inference.
    """
    if not data:
        raise ImageValidationError("invalid_image")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError("file_too_large", 413)

    expected_format = None
    if filename is not None:
        expected_format = EXTENSION_FORMATS.get(Path(filename).suffix.lower())
        if expected_format is None:
            raise ImageValidationError("unsupported_image_format", 415)

    try:
        with Image.open(BytesIO(data)) as image:
            detected_format = image.format
            if detected_format not in ALLOWED_FORMATS:
                raise ImageValidationError("unsupported_image_format", 415)
            if expected_format is not None and expected_format != detected_format:
                raise ImageValidationError("image_extension_mismatch")
            width, height = image.size
            if (
                width < 1
                or height < 1
                or width > MAX_IMAGE_SIDE
                or height > MAX_IMAGE_SIDE
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ImageValidationError("image_dimensions_exceeded", 413)
            image.verify()
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ImageValidationError("invalid_image") from None
