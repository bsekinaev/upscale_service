import io
import sys

import pytest
import redis

from app import app

sys.path.insert(0, '/app')


@pytest.fixture
def client():
    app.config['TESTING'] = True
    from celery_worker import app as celery_app
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True

    with app.test_client() as client:
        r_input = redis.Redis(host='redis', port=6379, db=1)
        r_input.flushdb()
        r_output = redis.Redis(host='redis', port=6379, db=2)
        r_output.flushdb()
        yield client


def test_upscale_no_file(client):
    resp = client.post('/upscale')
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_upscale_success(client):
    import cv2
    import numpy as np

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (25, 25), (75, 75), (255, 255, 255), -1)
    success, buffer = cv2.imencode('.png', img)
    img_bytes = buffer.tobytes()

    data = {'file': (io.BytesIO(img_bytes), 'test.png')}
    resp = client.post('/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 202
    json_data = resp.get_json()
    assert 'task_id' in json_data

    task_id = json_data['task_id']

    status_resp = client.get(f'/tasks/{task_id}')
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data['status'] == 'SUCCESS'
    assert 'download_url' in status_data

    dl_resp = client.get(f'/processed/{task_id}')
    assert dl_resp.status_code == 200
    assert dl_resp.mimetype == 'image/png'
    result_bytes = dl_resp.data
    assert len(result_bytes) > 0
