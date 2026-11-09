"""OpenCV inference with the same input boundaries enforced by the API."""

import cv2
import numpy as np
from cv2 import dnn_superres

from image_validation import MAX_IMAGE_PIXELS, MAX_IMAGE_SIDE, validate_image_bytes

_scaler = None


def _load_scaler(model_path: str = "EDSR_x2.pb"):
    global _scaler
    if _scaler is None:
        model = dnn_superres.DnnSuperResImpl_create()
        model.readModel(model_path)
        model.setModel("edsr", 2)
        _scaler = model
    return _scaler


def upscale_bytes(image_bytes: bytes, model_path: str = "EDSR_x2.pb") -> bytes:
    # Validate again at the worker boundary; queue payloads are untrusted.
    validate_image_bytes(image_bytes)
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("image_decode_failed")

    height, width = image.shape[:2]
    if (
        height > MAX_IMAGE_SIDE
        or width > MAX_IMAGE_SIDE
        or height * width > MAX_IMAGE_PIXELS
    ):
        raise ValueError("image_dimensions_exceeded")

    scaler = _load_scaler(model_path)
    result = scaler.upsample(image)
    success, encoded = cv2.imencode(".png", result)
    if not success:
        raise RuntimeError("image_encode_failed")
    return encoded.tobytes()
