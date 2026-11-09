"""HTTP API for bounded image uploads and asynchronous upscaling."""

import logging
import uuid
from io import BytesIO

import redis
from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from image_validation import ImageValidationError, MAX_IMAGE_BYTES, validate_image_bytes
from tasks import upscale_task

logger = logging.getLogger(__name__)
app = Flask(__name__)
# Multipart headers and boundaries need a little room beyond the file limit.
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 64 * 1024

redis_input = redis.Redis(host="redis", port=6379, db=1, socket_timeout=3)
redis_output = redis.Redis(host="redis", port=6379, db=2, socket_timeout=3)
INPUT_TTL_SECONDS = 3600


def valid_task_id(task_id: str) -> bool:
    try:
        parsed = uuid.UUID(task_id)
    except (TypeError, ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == task_id


def service_unavailable(operation: str, exc: Exception):
    logger.error(
        "upscale_dependency_failed operation=%s error_type=%s",
        operation,
        type(exc).__name__,
    )
    return jsonify({"error": "service_unavailable"}), 503


@app.after_request
def response_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(_exc):
    return jsonify({"error": "file_too_large"}), 413


@app.route("/upscale", methods=["POST"])
def upscale():
    if "file" not in request.files:
        return jsonify({"error": "no_file"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty_filename"}), 400

    # Never trust a file extension or client-reported Content-Type.
    image_bytes = file.stream.read(MAX_IMAGE_BYTES + 1)
    try:
        validate_image_bytes(image_bytes, filename=file.filename)
    except ImageValidationError as exc:
        return jsonify({"error": exc.code}), exc.status_code

    task_id = str(uuid.uuid4())
    try:
        redis_input.setex(task_id, INPUT_TTL_SECONDS, image_bytes)
    except Exception as exc:
        return service_unavailable("store_input", exc)

    try:
        upscale_task.apply_async(args=(task_id,), task_id=task_id)
    except Exception as exc:
        # Publishing and Redis deletion are not a transaction. A failed publish
        # is best-effort cleanup; leftover data always has a finite TTL.
        try:
            redis_input.delete(task_id)
        except redis.exceptions.RedisError:
            logger.warning("upscale_input_cleanup_failed task_id=%s", task_id)
        return service_unavailable("enqueue", exc)

    return jsonify({"task_id": task_id}), 202


@app.route("/tasks/<task_id>", methods=["GET"])
def get_task_state(task_id):
    if not valid_task_id(task_id):
        return jsonify({"error": "invalid_task_id"}), 400
    try:
        task = upscale_task.AsyncResult(task_id)
        state = task.state
    except Exception as exc:
        return service_unavailable("task_state", exc)

    if state == "SUCCESS":
        return jsonify({
            "status": "SUCCESS",
            "download_url": f"/processed/{task_id}",
        }), 200
    if state == "FAILURE":
        # task.info may contain stack traces, filesystem paths or secrets.
        return jsonify({"status": "FAILURE", "error": "processing_failed"}), 200
    if state in {"PENDING", "STARTED", "RETRY", "REVOKED"}:
        return jsonify({"status": state}), 200
    return jsonify({"status": "UNKNOWN"}), 200


@app.route("/processed/<file_id>", methods=["GET"])
def get_processed(file_id):
    if not valid_task_id(file_id):
        return jsonify({"error": "invalid_task_id"}), 400
    try:
        data = redis_output.get(file_id)
    except Exception as exc:
        return service_unavailable("get_result", exc)

    if data is None:
        try:
            state = upscale_task.AsyncResult(file_id).state
        except Exception as exc:
            return service_unavailable("get_task_state", exc)
        if state in {"PENDING", "STARTED", "RETRY"}:
            return jsonify({"error": "still_processing"}), 202
        return jsonify({"error": "file_not_found"}), 404

    return send_file(
        BytesIO(data),
        mimetype="image/png",
        as_attachment=True,
        download_name=f"{file_id}.png",
    )
