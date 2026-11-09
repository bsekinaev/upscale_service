"""Celery task: never expose raw processing exceptions to API clients."""

import logging

import redis

from celery_worker import app
from upscale import upscale_bytes

logger = logging.getLogger(__name__)
redis_input = redis.Redis(host="redis", port=6379, db=1, socket_timeout=3)
redis_output = redis.Redis(host="redis", port=6379, db=2, socket_timeout=3)
RESULT_TTL_SECONDS = 3600


@app.task(bind=True, max_retries=0)
def upscale_task(self, task_id: str):
    try:
        input_data = redis_input.get(task_id)
        if input_data is None:
            raise ValueError("input_expired_or_missing")

        output_data = upscale_bytes(input_data)
        redis_output.setex(task_id, RESULT_TTL_SECONDS, output_data)
        return {"status": "SUCCESS", "task_id": task_id}
    except Exception as exc:
        logger.error(
            "upscale_task_failed task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        # Celery's result backend stores failure information. Do not store
        # arbitrary OpenCV / Redis exception strings there or in another key.
        raise RuntimeError("processing_failed") from None
    finally:
        try:
            redis_input.delete(task_id)
        except redis.exceptions.RedisError:
            # A stale input expires by TTL; deleting it must not turn a
            # successfully published output into an apparent failed task.
            logger.warning("upscale_input_cleanup_failed task_id=%s", task_id)
