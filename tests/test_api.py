"""Offline API and worker regression tests, with no live Redis or EDSR inference."""

import io
import logging
from unittest.mock import patch

import pytest
from PIL import Image

import app as api
import tasks as worker
from celery_worker import app as celery_app


class FakeRedis:
    """Small deterministic key/value fake: no DB flushing or network access."""

    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        assert ttl > 0
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)


def png_bytes(width=16, height=16):
    output = io.BytesIO()
    Image.new("RGB", (width, height), (120, 20, 30)).save(output, format="PNG")
    return output.getvalue()


def upload(client, data=None, name="test.png"):
    if data is None:
        data = png_bytes()
    return client.post(
        "/upscale",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


@pytest.fixture
def client(monkeypatch):
    incoming = FakeRedis()
    outgoing = FakeRedis()
    monkeypatch.setattr(api, "redis_input", incoming)
    monkeypatch.setattr(api, "redis_output", outgoing)
    monkeypatch.setattr(worker, "redis_input", incoming)
    monkeypatch.setattr(worker, "redis_output", outgoing)

    # Run Celery without Redis or subprocesses, retaining actual task states.
    celery_app.conf.update(
        task_always_eager=True,
        task_store_eager_result=True,
        result_backend="cache+memory://",
        task_eager_propagates=False,
    )
    monkeypatch.setattr(worker, "upscale_bytes", lambda data: png_bytes(32, 32))
    api.app.config.update(TESTING=True)
    with api.app.test_client() as test_client:
        yield test_client, incoming, outgoing


def test_no_file_and_empty_filename(client):
    test_client, _, _ = client
    assert test_client.post("/upscale").status_code == 400
    response = test_client.post(
        "/upscale",
        data={"file": (io.BytesIO(b""), "")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_rejects_non_image_and_extension_mismatch(client):
    test_client, incoming, _ = client
    assert upload(test_client, b"not an image").status_code == 400
    wrong = upload(test_client, png_bytes(), name="fake.jpg")
    assert wrong.status_code == 400
    assert wrong.get_json()["error"] == "image_extension_mismatch"
    assert incoming.values == {}


def test_rejects_disallowed_extension(client):
    test_client, _, _ = client
    response = upload(test_client, png_bytes(), name="notes.txt")
    assert response.status_code == 415


def test_rejects_large_file_without_storing(client, monkeypatch):
    test_client, incoming, _ = client
    monkeypatch.setattr(api, "MAX_IMAGE_BYTES", 64)
    import image_validation
    monkeypatch.setattr(image_validation, "MAX_IMAGE_BYTES", 64)
    api.app.config["MAX_CONTENT_LENGTH"] = 64 + 64 * 1024
    result = upload(test_client, png_bytes())
    assert result.status_code == 413
    assert incoming.values == {}


def test_rejects_large_multipart_request(client):
    test_client, incoming, _ = client
    old = api.app.config["MAX_CONTENT_LENGTH"]
    api.app.config["MAX_CONTENT_LENGTH"] = 256
    try:
        response = upload(test_client, png_bytes())
        assert response.status_code == 413
        assert response.get_json()["error"] == "file_too_large"
        assert incoming.values == {}
    finally:
        api.app.config["MAX_CONTENT_LENGTH"] = old


def test_successful_upload_task_state_and_download(client):
    test_client, incoming, outgoing = client
    response = upload(test_client)
    assert response.status_code == 202
    task_id = response.get_json()["task_id"]
    assert not incoming.values
    assert task_id in outgoing.values
    status = test_client.get(f"/tasks/{task_id}")
    assert status.status_code == 200
    assert status.get_json()["status"] == "SUCCESS"
    result = test_client.get(f"/processed/{task_id}")
    assert result.status_code == 200
    assert result.mimetype == "image/png"
    assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Content-Type-Options"] == "nosniff"


def test_invalid_task_ids_are_not_queried(client):
    test_client, _, _ = client
    assert test_client.get("/tasks/invalid").status_code == 400
    assert test_client.get("/processed/invalid").status_code == 400


def test_enqueue_failure_cleans_up_input_and_hides_exception(client, monkeypatch, caplog):
    test_client, incoming, _ = client
    leaked_value = "redis://secret-password@redis:6379"
    with patch.object(
        api.upscale_task, "apply_async", side_effect=RuntimeError(leaked_value)
    ):
        with caplog.at_level(logging.ERROR):
            response = upload(test_client)
    assert response.status_code == 503
    assert response.get_json() == {"error": "service_unavailable"}
    assert incoming.values == {}
    assert leaked_value not in caplog.text


def test_redis_store_error_returns_sanitized_503(client, monkeypatch):
    test_client, incoming, _ = client
    monkeypatch.setattr(
        incoming,
        "setex",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret-redis-uri")),
    )
    response = upload(test_client)
    assert response.status_code == 503
    assert response.get_json()["error"] == "service_unavailable"


def test_processing_failure_does_not_leak_task_details(client, monkeypatch, caplog):
    test_client, _, _ = client
    secret = "SECRET_MODEL_PATH_OR_TOKEN"
    monkeypatch.setattr(
        worker,
        "upscale_bytes",
        lambda _: (_ for _ in ()).throw(ValueError(secret)),
    )
    with caplog.at_level(logging.ERROR):
        response = upload(test_client)
    assert response.status_code == 202
    task_id = response.get_json()["task_id"]
    result = test_client.get(f"/tasks/{task_id}")
    assert result.get_json() == {"status": "FAILURE", "error": "processing_failed"}
    assert secret not in caplog.text


def test_worker_releases_input_even_when_processing_fails(client, monkeypatch):
    _, incoming, outgoing = client
    identifier = "test-job"
    incoming.setex(identifier, 3600, png_bytes())
    monkeypatch.setattr(
        worker, "upscale_bytes", lambda _: (_ for _ in ()).throw(ValueError("bad"))
    )
    with pytest.raises(RuntimeError, match="processing_failed"):
        worker.upscale_task.run(identifier)
    assert incoming.get(identifier) is None
    assert outgoing.get(identifier) is None


def test_healthcheck_is_liveness_only(client):
    test_client, _, _ = client
    response = test_client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
