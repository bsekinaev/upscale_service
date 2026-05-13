import redis

from celery_worker import app
from upscale import upscale_bytes

redis_input = redis.StrictRedis(host='redis', port=6379, db=1)
redis_output = redis.StrictRedis(host='redis', port=6379, db=2)


@app.task(bind=True, max_retries=3)
def upscale_task(self, task_id: str):
    input_data = redis_input.get(task_id)
    if input_data is None:
        raise Exception(f'Входные данные для задачи {task_id} не найдены')

    try:
        output_data = upscale_bytes(input_data)
        redis_output.setex(task_id, 3600, output_data)
        return {'status': 'SUCCESS', 'task_id': task_id}

    except Exception as e:
        redis_output.setex(f'error:{task_id}', 3600, str(e))
        raise
    finally:
        redis_input.delete(task_id)
