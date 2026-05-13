import cv2
import numpy as np
from cv2 import dnn_superres

_scaler = None


def _load_scaler(model_path: str = 'EDSR_x2.pb'):
    global _scaler
    if _scaler is None:
        _scaler = dnn_superres.DnnSuperResImpl_create()
        _scaler.readModel(model_path)
        _scaler.setModel('edsr', 2)
    return _scaler


def upscale_bytes(image_bytes: bytes, model_path: str = 'EDSR_x2.pb') -> bytes:
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Не удалось декодировать изображение')

    scaler = _load_scaler(model_path)
    result = scaler.upsample(image)

    success, encoded = cv2.imencode('.png', result)
    if not success:
        raise RuntimeError('Не удалось закодировать выходное изображение')
    return encoded.tobytes()
